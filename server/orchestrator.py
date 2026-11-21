"""Runs the agents in order and emits events as each result lands."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

from . import llm, references
from .agents import extractor, modeller, questioner, researcher, sceptic
from .evaluator import evaluate
from .fetch import fetch
from .llm import SearchUnavailable
from .memory import Memory, Record, diff
from .references import References
from .schema import Claim, ModellerOut, Node, Objection, Verdict
from .store import RunLog

LABEL = "Illustrative, public data only; not Blume's or the company's figures"
COMPARABLES_PER_GUESS = 2
COMPARABLES_MAX = 8


@dataclass
class RunState:
    company: str = ""
    claims: list[Claim] = field(default_factory=list)
    objections: list[Objection] = field(default_factory=list)
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    model: ModellerOut | None = None
    revision: int = 0
    refs: References | None = None
    history: list[Record] = field(default_factory=list)  # latest earlier look at this company
    recalled: dict[str, Record] = field(default_factory=dict)  # every memory shown to the model, by id


STATES: dict[str, RunState] = {}


def topo(model: ModellerOut) -> list[Node]:
    """Children before parents, so the tree grows from inputs to roots."""
    nodes = {n.id: n for n in model.tree.nodes}
    order: list[Node] = []
    seen: set[str] = set()

    def visit(nid: str) -> None:
        if nid in seen:
            return
        seen.add(nid)
        for c in nodes[nid].children:
            visit(c)
        order.append(nodes[nid])

    for n in model.tree.nodes:
        visit(n.id)
    return order


def _emit_repair(log: RunLog, found: list[str]) -> None:
    """Show on the canvas that the checks sent the model back, and why."""
    log.emit("agent_started", "modeller", repair=found,
             instruction="Checks rejected the model and sent it back: " + " | ".join(found))


def history_block(company: str, recs: list[Record]) -> str:
    if not recs:
        return f"No earlier looks at {company} in memory. This is the first."
    lines = [f"Earlier look at {company} on {recs[0].run_date} ({recs[0].source_url}):"]
    for kind, title in (("assumption", "Assumptions then"), ("claim", "Claims and verdicts then"),
                        ("question", "Questions asked then")):
        rows = [r for r in recs if r.kind == kind]
        if rows:
            lines.append(f"{title}:")
            lines += [f"- [{r.id}] {r.summary}" for r in rows]
    return "\n".join(lines)


def comparables_block(found: list[tuple[str, Record, float]]) -> str:
    return "\n".join(
        f"- [{r.id}] for your '{label}': {r.company} ({r.run_date}) used {r.summary} (similarity {score:.2f})"
        for label, r, score in found
    )


def _recall(log: RunLog, st: RunState, role: str, r: Record, score: float | None = None, for_label: str = "") -> None:
    if r.id in st.recalled:
        return
    st.recalled[r.id] = r
    log.emit("memory_recalled", "memory", role=role, record=r.public(), score=score, for_label=for_label)


def _emit_model(log: RunLog, st: RunState) -> None:
    m = st.model
    assert m is not None
    for a in m.assumptions:
        log.emit("assumption_added", "modeller", revision=st.revision, assumption=a.model_dump())
    for n in topo(m):
        log.emit("tree_node_added", "modeller", revision=st.revision, node=n.model_dump(),
                 is_value_root=n.id == m.tree.root_value_id, is_impact_root=n.id == m.tree.root_impact_id)
    ev = evaluate(m.tree, m.assumptions)
    log.emit("tree_evaluated", "evaluator", revision=st.revision, tree=m.tree.model_dump(),
             evaluation=ev.model_dump(), rationale=m.rationale)
    log.emit("agent_finished", "modeller")

    log.emit("agent_started", "questioner")
    asked = [r for r in st.history if r.kind == "question"]
    for q in questioner.run(st.company, m.assumptions, ev, st.objections, asked):
        log.emit("question_added", "questioner", revision=st.revision, question=q.model_dump())
    log.emit("agent_finished", "questioner")


def _since_last_look(log: RunLog, st: RunState, mem: Memory) -> None:
    if not st.history or not st.model:
        return
    qs = [e["payload"]["question"] for e in log.events
          if e["type"] == "question_added" and e["payload"].get("revision") == st.revision]
    d = diff(st.history, [c.model_dump() for c in st.claims], {k: v.model_dump() for k, v in st.verdicts.items()},
             [a.model_dump() for a in st.model.assumptions], qs, mem.embedder)
    if d:
        log.emit("memory_diff", "memory", diff=d)


def _remember(run_id: str, mem: Memory) -> None:
    """Store this run so the next look starts from it. Never fails the run."""
    try:
        mem.add_run(RunLog(run_id).events)
        mem.save()
    except Exception as e:  # pragma: no cover - logged, not fatal
        print(f"memory: could not store run {run_id}: {e}", file=sys.stderr)


def run(run_id: str, url: str) -> None:
    log = RunLog(run_id)
    st = STATES.setdefault(run_id, RunState())
    llm.FALLBACK_USED.clear()
    try:
        log.emit("run_started", url=url, mode="live", label=LABEL)

        log.emit("agent_started", "extractor")
        title, text = fetch(url)
        st.company, st.claims, dropped = extractor.run(url, title, text)
        log.emit("agent_finished", "extractor", company=st.company, page_title=title,
                 dropped=[{"text": c.text, "quote": c.quote} for c in dropped])
        for c in st.claims:
            log.emit("claim_added", "extractor", claim=c.model_dump())
        if not st.claims:
            raise RuntimeError("No claims with verifiable quotes were found on the page.")

        # Memory: what do we already know about this company?
        log.emit("agent_started", "memory", instruction=f"Looking up earlier assessments of {st.company}")
        mem = Memory()
        looks = mem.runs(st.company, exclude_run=run_id)
        if looks:
            last_run = looks[0][0]
            st.history = [r for r in mem.history(st.company, exclude_run=run_id) if r.run_id == last_run]
            for r in st.history:
                _recall(log, st, "history", r)
            note = (f"Recalled {len(st.history)} items from the last look at {st.company} on {looks[0][1]}"
                    + (f" ({len(looks)} earlier looks in total)." if len(looks) > 1 else "."))
        else:
            note = f"No earlier looks at {st.company} in memory. Starting fresh."
        log.emit("agent_finished", "memory", note=note)

        search_ok = True
        for c in st.claims:
            evidence = []
            if search_ok:
                log.emit("agent_started", "researcher", claim_id=c.id)
                try:
                    evidence = researcher.run(st.company, c)
                except SearchUnavailable as e:
                    search_ok = False
                    log.emit("agent_finished", "researcher", search_unavailable=True,
                             note=f"Web search unavailable ({e}). Claims are judged without independent evidence.")
                for e in evidence:
                    log.emit("evidence_added", "researcher", evidence=e.model_dump())

            log.emit("agent_started", "sceptic", claim_id=c.id)
            objs, verdict = sceptic.run(st.company, c, evidence)
            st.objections += objs
            st.verdicts[c.id] = verdict
            for o in objs:
                log.emit("objection_added", "sceptic", objection=o.model_dump())
            log.emit("verdict_set", "sceptic", verdict=verdict.model_dump())

        log.emit("agent_started", "modeller")
        st.refs = references.load(live_fx=True)
        repair = lambda found: _emit_repair(log, found)  # noqa: E731
        draft = modeller.run(st.company, st.claims, st.verdicts, st.objections, st.refs,
                             history=history_block(st.company, st.history), memory=st.recalled,
                             on_repair=repair)

        # Memory: how did we size these guesses at other companies?
        # Every remaining guess, including ones carried over from the last look: a guess repeated is still a guess.
        # Sourced values are not guesses, and carry_over_sources keeps them sourced.
        guesses = [a for a in draft.assumptions
                   if a.judgement_call and "conversion" not in (a.source_note or "").lower()]
        found: list[tuple[str, Record, float]] = []
        if guesses and mem.records:
            log.emit("agent_started", "memory", instruction=f"Finding how the firm sized {len(guesses)} judgement calls before")
            floor = mem.embedder.match_threshold * 0.75
            for a in guesses:
                for r, score in mem.search([f"{a.label} [{a.unit}]"], k=COMPARABLES_PER_GUESS,
                                           exclude_company=st.company, min_score=floor, unit=a.unit):
                    if r.id not in {f[1].id for f in found}:
                        found.append((a.label, r, score))
            found = sorted(found, key=lambda f: -f[2])[:COMPARABLES_MAX]
            for label, r, score in found:
                _recall(log, st, "comparable", r, score, label)
            log.emit("agent_finished", "memory",
                     note=f"Found {len(found)} comparable sizings from other companies." if found
                     else "No close comparables in memory for these judgement calls.")

        if found:
            log.emit("agent_started", "modeller", instruction="Anchoring judgement calls to the firm's earlier sizings")
            st.model = modeller.anchor(draft, comparables_block(found), st.refs, st.claims,
                                       memory=st.recalled, on_repair=repair)
        else:
            st.model = draft
        _emit_model(log, st)
        _since_last_look(log, st, mem)
        log.emit("run_finished", models={"main": llm.MODEL_FAST, "strong": llm.MODEL_STRONG,
                                         "fallback_calls": len(llm.FALLBACK_USED)})
        _remember(run_id, mem)
    except Exception as e:  # surface every failure on the canvas
        log.emit("error", message=f"{type(e).__name__}: {e}")


def whatif(run_id: str, instruction: str) -> None:
    log = RunLog(run_id)
    st = STATES.get(run_id)
    if not st or not st.model:
        log.emit("error", message="This run has no live model to change (replays are read-only).")
        return
    try:
        log.emit("agent_started", "modeller", instruction=instruction)
        st.model = modeller.patch(instruction, st.model, st.refs or references.load(), st.claims,
                                  memory=st.recalled, on_repair=lambda found: _emit_repair(log, found))
        st.revision += 1
        _emit_model(log, st)
        log.emit("run_finished")
        _remember(run_id, Memory())  # the analyst's change becomes what the next look starts from
    except Exception as e:
        log.emit("error", message=f"{type(e).__name__}: {e}")
