"""Modeller: claims + verdicts -> assumptions and a driver tree with two roots.

The evaluator validates the tree; on failure the Modeller gets one repair attempt.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .. import llm
from ..evaluator import TreeError, validate
from ..schema import Claim, ModellerOut, Objection, Verdict
from . import prompt

FACTORS = Path(__file__).resolve().parents[2] / "factors" / "uk_ghg_2025_vehicles.csv"
FACTOR_URL = "https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025"


def factor_table() -> str:
    with FACTORS.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return "\n".join(
        f"- {r['vehicle']}, {r['size']}, {r['fuel']}: {r['factor_2025']} kg CO2e per {r['unit']} (row {r['id']})"
        for r in rows
    )


def _claims_block(claims: list[Claim], verdicts: dict[str, Verdict], objections: list[Objection]) -> str:
    lines = []
    for c in claims:
        v = verdicts.get(c.id)
        lines.append(f"- {c.id} [{c.kind}] {c.text} | quote: \"{c.quote}\" | verdict: {v.status if v else 'n/a'}")
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


def check(out: ModellerOut) -> None:
    """Generic tree checks, plus the rule this demo exists to show: one shared driver."""
    validate(out.tree, out.assumptions)
    shared = _inputs_under(out.tree, out.tree.root_value_id) & _inputs_under(out.tree, out.tree.root_impact_id)
    if not shared:
        raise TreeError(
            "the value root and the impact root share no input. Derive both from the same physical driver "
            "(for example: attributable miles avoided -> visits avoided -> GBP, and the same miles -> tCO2e)"
        )


def _repair(p: str) -> ModellerOut:
    out = llm.generate_json(p, ModellerOut, model=llm.MODEL_STRONG)
    try:
        check(out)
        return out
    except TreeError as e:
        out = llm.generate_json(
            f"{p}\n\nYour previous model was rejected by the evaluator: {e}\n"
            f"Previous model:\n{out.model_dump_json()}\nReturn a corrected model.",
            ModellerOut, model=llm.MODEL_STRONG,
        )
        check(out)
        return out


def run(company: str, claims: list[Claim], verdicts: dict[str, Verdict], objections: list[Objection]) -> ModellerOut:
    return _repair(prompt("modeller", company=company, claims=_claims_block(claims, verdicts, objections),
                          factors=factor_table(), factor_url=FACTOR_URL))


def patch(instruction: str, current: ModellerOut) -> ModellerOut:
    return _repair(prompt(
        "modeller_patch", instruction=instruction,
        assumptions=json.dumps([a.model_dump() for a in current.assumptions], indent=1),
        tree=current.tree.model_dump_json(indent=1),
    ))
