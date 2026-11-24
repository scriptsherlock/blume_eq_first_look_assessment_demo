"""Modeller: claims + verdicts -> assumptions and a driver tree with two roots.

Code checks every model before it is used: tree structure, one shared driver,
currencies, emission factors and exchange rates (see guardrails.py). Any
failures go back to the Modeller as repair instructions, up to MAX_REPAIRS.
"""
from __future__ import annotations

import json
import re

from .. import guardrails, llm
from ..evaluator import TreeError, validate
from ..references import References
from ..schema import Claim, ModellerOut, Objection, Verdict
from . import prompt

MAX_REPAIRS = 2


def _claims_block(claims: list[Claim], verdicts: dict[str, Verdict], objections: list[Objection]) -> str:
    lines = []
    for c in claims:
        v = verdicts.get(c.id)
        qty = f" | quantity: {c.quantity} {c.unit or ''}" if c.quantity is not None else ""
        lines.append(f"- {c.id} [{c.kind}] {c.text} | quote: \"{c.quote}\"{qty} | verdict: {v.status if v else 'n/a'}")
        for o in objections:
            if o.claim_id == c.id:
                lines.append(f"    objection (severity {o.severity}): {o.text}")
    return "\n".join(lines)


def _inputs_under(tree, root: str) -> set[str]:
    nodes = {n.id: n for n in tree.nodes}
    seen, stack, inputs = set(), [root], set()
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in nodes:
            continue
        seen.add(nid)
        if nodes[nid].op == "input":
            inputs.add(nid)
        stack.extend(nodes[nid].children)
    return inputs


def _shared_driver(out: ModellerOut) -> None:
    value_in = _inputs_under(out.tree, out.tree.root_value_id)
    impact_in = _inputs_under(out.tree, out.tree.root_impact_id)
    if not value_in & impact_in:
        raise TreeError(
            "the value root and the impact root share no input. Derive both from the same physical driver "
            "(for example: attributable miles avoided -> visits avoided -> GBP, and the same miles -> tCO2e)"
        )
    # Credit for causing the effect must be the same for money and carbon.
    labels = {a.id: a.label for a in out.assumptions}
    for n in out.tree.nodes:
        if n.op == "input" and "attribut" in labels.get(n.assumption_id or "", "").lower():
            if (n.id in value_in) != (n.id in impact_in):
                raise TreeError(
                    f"the attribution share ({n.assumption_id}) feeds only one of the two roots. Apply it to the "
                    "shared driver so the customer value and the emissions avoided give the product the same credit."
                )


def _no_dead_ends(out: ModellerOut) -> None:
    """Every node must feed a root. A step worked out and then ignored usually means a wrong link."""
    nodes = {n.id: n for n in out.tree.nodes}
    seen, stack = set(), [out.tree.root_value_id, out.tree.root_impact_id]
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in nodes:
            continue
        seen.add(nid)
        stack.extend(nodes[nid].children)
    unused = [n for n in out.tree.nodes if n.id not in seen]
    if unused:
        names = ", ".join(f"{n.id} ('{n.label}')" for n in unused)
        raise TreeError(
            f"{names} feed{'s' if len(unused) == 1 else ''} neither root. Either use it where it belongs "
            "(for example, multiply visits avoided by cost per visit) or remove it."
        )


MEM_ID = re.compile(r"mem-[0-9a-f]{8}")


def carry_over_sources(out: ModellerOut, memory: dict) -> None:
    """An assumption that cites an earlier look's *sourced* value keeps that source.

    Without this, a model that forgets to copy the URL gets flagged as unsourced and
    "repairs" it by turning a company claim into a guess. Runs before the checks.
    """
    for a in out.assumptions:
        if a.source_url:
            continue
        for mid in MEM_ID.findall(a.source_note or ""):
            r = memory.get(mid)
            prev = (r.data.get("assumption") if r is not None and r.kind == "assumption" else None) or {}
            if prev and not prev.get("judgement_call") and prev.get("source_url"):
                a.source_url = prev["source_url"]
                a.claim_ids = a.claim_ids or []
                a.judgement_call = False
                break


def _memory_citations(out: ModellerOut, memory_ids) -> None:
    for a in out.assumptions:
        for mid in MEM_ID.findall(a.source_note or ""):
            if mid not in memory_ids:
                raise TreeError(
                    f"assumption {a.id} cites {mid}, which is not one of the memories you were given. "
                    "Cite only ids from the memory lists, or remove the citation."
                )


def problems(out: ModellerOut, refs: References | None = None, claims: list[Claim] = (),
             memory=None) -> list[str]:
    """Every rule the model breaks, as repair instructions. Empty means the model is accepted."""
    if refs is not None:
        guardrails.fill_sources(out, refs)
    if isinstance(memory, dict):
        carry_over_sources(out, memory)
    try:
        validate(out.tree, out.assumptions)
    except TreeError as e:
        return [str(e)]  # the other checks need a sound tree
    found = []
    checks = [_shared_driver, _no_dead_ends, guardrails.check_units]
    if refs is not None:
        checks += [lambda o: guardrails.check_currency(o, list(claims)), lambda o: guardrails.check_factors(o, refs)]
    if memory is not None:
        checks.append(lambda o: _memory_citations(o, memory))
    for c in checks:
        try:
            c(out)
        except TreeError as e:
            found.append(str(e))
    return found


def check(out: ModellerOut, refs: References | None = None, claims: list[Claim] = (),
          memory=None) -> None:
    found = problems(out, refs, claims, memory)
    if found:
        raise TreeError("; ".join(found))


def _build(p: str, refs: References | None, claims: list[Claim], on_repair=None,
           memory=None) -> ModellerOut:
    out = llm.generate_json(p, ModellerOut, model=llm.MODEL_STRONG)
    for _ in range(MAX_REPAIRS):
        found = problems(out, refs, claims, memory)
        if not found:
            return out
        if on_repair:
            on_repair(found)
        fixes = "\n".join(f"- {f}" for f in found)
        out = llm.generate_json(
            f"{p}\n\nYour previous model was rejected by the checks:\n{fixes}\n"
            f"Previous model:\n{out.model_dump_json()}\nReturn a corrected model.",
            ModellerOut, model=llm.MODEL_STRONG,
        )
    check(out, refs, claims, memory)
    return out


def run(company: str, claims: list[Claim], verdicts: dict[str, Verdict], objections: list[Objection],
        refs: References, history: str = "", memory=None, on_repair=None) -> ModellerOut:
    p = prompt("modeller", company=company, claims=_claims_block(claims, verdicts, objections),
               references=refs.prompt_block(), history=history or "No earlier looks in memory.")
    return _build(p, refs, claims, on_repair, memory)


def anchor(draft: ModellerOut, comparables: str, refs: References, claims: list[Claim],
           memory=None, on_repair=None) -> ModellerOut:
    """Second pass: revisit judgement calls in the light of how the firm sized similar things before."""
    p = prompt("modeller_anchor", comparables=comparables, model=draft.model_dump_json(indent=1),
               references=refs.prompt_block())
    return _build(p, refs, claims, on_repair, memory)


def patch(instruction: str, current: ModellerOut, refs: References, claims: list[Claim],
          memory=None, on_repair=None) -> ModellerOut:
    p = prompt(
        "modeller_patch", instruction=instruction,
        assumptions=json.dumps([a.model_dump() for a in current.assumptions], indent=1),
        tree=current.tree.model_dump_json(indent=1),
        references=refs.prompt_block(),
    )
    return _build(p, refs, claims, on_repair, memory)
