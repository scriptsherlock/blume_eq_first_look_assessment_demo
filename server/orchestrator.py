"""Runs the agents in order and emits events as each result lands."""
from __future__ import annotations

from dataclasses import dataclass, field

from .agents import extractor, modeller, questioner, researcher, sceptic
from . import llm
from .llm import SearchUnavailable
from .evaluator import evaluate
from .fetch import fetch
from .schema import Claim, ModellerOut, Node, Objection, Verdict
from .store import RunLog

LABEL = "Illustrative, public data only; not Blume's or the company's figures"


@dataclass
class RunState:
    company: str = ""
    claims: list[Claim] = field(default_factory=list)
    objections: list[Objection] = field(default_factory=list)
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    model: ModellerOut | None = None
    revision: int = 0


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
    for q in questioner.run(st.company, m.assumptions, ev, st.objections):
        log.emit("question_added", "questioner", revision=st.revision, question=q.model_dump())
    log.emit("agent_finished", "questioner")


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
        st.model = modeller.run(st.company, st.claims, st.verdicts, st.objections)
        _emit_model(log, st)
        log.emit("run_finished", models={"main": llm.MODEL_FAST, "strong": llm.MODEL_STRONG,
                                         "fallback_calls": len(llm.FALLBACK_USED)})
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
        st.model = modeller.patch(instruction, st.model)
        st.revision += 1
        _emit_model(log, st)
        log.emit("run_finished")
    except Exception as e:
        log.emit("error", message=f"{type(e).__name__}: {e}")
