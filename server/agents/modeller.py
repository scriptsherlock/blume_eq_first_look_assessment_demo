"""Modeller: claims + verdicts -> assumptions and a driver tree with two roots.

Code checks every model before it is used: tree structure, one shared driver,
currencies, emission factors and exchange rates (see guardrails.py). Any
failures go back to the Modeller as repair instructions, up to MAX_REPAIRS.
"""
from __future__ import annotations

import json

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


def problems(out: ModellerOut, refs: References | None = None, claims: list[Claim] = ()) -> list[str]:
    """Every rule the model breaks, as repair instructions. Empty means the model is accepted."""
    if refs is not None:
        guardrails.fill_sources(out, refs)
    try:
        validate(out.tree, out.assumptions)
    except TreeError as e:
        return [str(e)]  # the other checks need a sound tree
    found = []
    checks = [_shared_driver]
    if refs is not None:
        checks += [lambda o: guardrails.check_currency(o, list(claims)), lambda o: guardrails.check_factors(o, refs)]
    for c in checks:
        try:
            c(out)
        except TreeError as e:
            found.append(str(e))
    return found


def check(out: ModellerOut, refs: References | None = None, claims: list[Claim] = ()) -> None:
    found = problems(out, refs, claims)
    if found:
        raise TreeError("; ".join(found))


def _build(p: str, refs: References | None, claims: list[Claim], on_repair=None) -> ModellerOut:
    out = llm.generate_json(p, ModellerOut, model=llm.MODEL_STRONG)
    for _ in range(MAX_REPAIRS):
        found = problems(out, refs, claims)
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
    check(out, refs, claims)
    return out


def run(company: str, claims: list[Claim], verdicts: dict[str, Verdict], objections: list[Objection],
        refs: References, on_repair=None) -> ModellerOut:
    p = prompt("modeller", company=company, claims=_claims_block(claims, verdicts, objections),
               references=refs.prompt_block())
    return _build(p, refs, claims, on_repair)


def patch(instruction: str, current: ModellerOut, refs: References, claims: list[Claim], on_repair=None) -> ModellerOut:
    p = prompt(
        "modeller_patch", instruction=instruction,
        assumptions=json.dumps([a.model_dump() for a in current.assumptions], indent=1),
        tree=current.tree.model_dump_json(indent=1),
        references=refs.prompt_block(),
    )
    return _build(p, refs, claims, on_repair)
