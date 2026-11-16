"""Build a hand-authored sample replay for the Vyntelligence case.

This exists so the canvas can be developed and demoed before a live Gemini
run is recorded. The claims, objections, verdicts, model structure and
questions below are written by hand, not by a model, and the replay says so.
Every number in `tree_evaluated` is still computed by the evaluator, and every
quote is checked against the saved source page.

Replace it with a live run:  python -m scripts.record_replay <url> vyntelligence
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.evaluator import evaluate  # noqa: E402
from server.fetch import quote_in_text  # noqa: E402
from server.orchestrator import LABEL, topo  # noqa: E402
from server.schema import (  # noqa: E402
    Assumption, Claim, DriverTree, Evidence, ModellerOut, Node, Objection, Question, Verdict,
)

URL = ("https://www.blumeequity.com/insights/"
       "transforming-field-operations-through-video-intelligence-why-we-partnered-with-vyntelligence")
FACTOR_URL = "https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025"
COMPANY = "Vyntelligence"

claims = [
    Claim(id="c1", kind="impact", quantity=4_000_000, unit="carbon miles / yr", source_url=URL,
          text="Halving field visits saves about 4 million carbon miles a year across Vyntelligence deployments.",
          quote="reducing field visits by 50% saves approximately 4 million carbon miles annually"),
    Claim(id="c2", kind="value", quantity=57, unit="% fewer visits", source_url=URL,
          text="One UK energy company cut physical visits by 57% as customers chose video surveys.",
          quote="another UK energy company reducing visits by 57%"),
    Claim(id="c3", kind="value", quantity=85, unit="% fewer fines", source_url=URL,
          text="A major UK utility cut fines by 85% by detecting permit, compliance and safety risks automatically.",
          quote="achieve an 85% fines reduction and eliminate audits"),
    Claim(id="c4", kind="impact", source_url=URL,
          text="Faster leak detection has conserved millions of gallons of water.",
          quote="have already conserved millions of gallons of water"),
    Claim(id="c5", kind="market", quantity=70, unit="% of field service tasks", source_url=URL,
          text="McKinsey estimates up to 70% of field service tasks could be automated with AI workflows.",
          quote="could automate up to 70% of field service tasks"),
]

evidence = [
    Evidence(id="e_c1_1", claim_id="c1", stance="context", publisher="GOV.UK (DESNZ)", url=FACTOR_URL,
             summary="UK 2025 conversion factors give 0.411 kg CO2e per mile for an average diesel van and "
                     "0.269 kg for an average car, so 4M miles is roughly 1,100-1,650 tCO2e depending on vehicle."),
]

objections = [
    Objection(id="o_c1_1", claim_id="c1", severity=3,
              text="'Carbon miles' is undefined: vehicle miles, or miles weighted by something? And the 50% "
                   "reduction is a condition, not a measured result. Which deployments, over what period?",
              what_would_resolve_it="Deployment-level data: visits before and after, average round-trip miles, "
                                    "vehicle mix, and the period measured."),
    Objection(id="o_c1_2", claim_id="c1", severity=2,
              text="Attribution: some visits would have been cut anyway (remote diagnostics, scheduling changes).",
              what_would_resolve_it="A control group or pre-period trend for at least one customer."),
    Objection(id="o_c2_1", claim_id="c2", severity=2,
              text="One customer's result. Survey visits may be the easiest visit type to replace; it says "
                   "little about repair or install visits.",
              what_would_resolve_it="Visit reduction by visit type across the top 10 customers."),
    Objection(id="o_c3_1", claim_id="c3", severity=2,
              text="Fines are lumpy and depend on the regulator's enforcement year; 85% may be one good year.",
              what_would_resolve_it="Three years of fines data for that customer and the regulator's "
                                    "enforcement trend."),
    Objection(id="o_c4_1", claim_id="c4", severity=1,
              text="No number, customer or method. Cannot be modelled.",
              what_would_resolve_it="Leak volumes detected earlier, and the time saved per leak."),
    Objection(id="o_c5_1", claim_id="c5", severity=1,
              text="A market estimate about the sector, not a Vyntelligence result.",
              what_would_resolve_it="None needed for the model; treat as context."),
]

verdicts = [
    Verdict(claim_id="c1", status="needs evidence",
            reason="Plausible order of magnitude, but undefined unit and no measured baseline."),
    Verdict(claim_id="c2", status="needs evidence", reason="Single customer, single visit type."),
    Verdict(claim_id="c3", status="needs evidence", reason="Single customer, fines are volatile."),
    Verdict(claim_id="c4", status="needs evidence", reason="No quantity given."),
    Verdict(claim_id="c5", status="not attributable", reason="Sector estimate, not a company result."),
]

assumptions = [
    Assumption(id="a1", label="Vehicle miles avoided per year (all deployments)", low=3_000_000, base=4_000_000,
               high=4_500_000, unit="miles/yr", source_url=URL, claim_ids=["c1"],
               source_note="Company claim via Blume's post; range reflects 'approximately'."),
    Assumption(id="a2", label="Share of avoided miles attributable to the product", low=0.3, base=0.6, high=0.9,
               unit="ratio", judgement_call=True),
    Assumption(id="a3", label="Average round-trip miles per field visit", low=10, base=20, high=40,
               unit="miles/visit", judgement_call=True),
    Assumption(id="a4", label="Fully loaded cost of one field visit", low=80, base=150, high=300,
               unit="GBP/visit", judgement_call=True),
    Assumption(id="a5", label="Emission factor per vehicle mile", low=0.26915, base=0.41138, high=0.41138,
               unit="kgCO2e/mile", source_url=FACTOR_URL,
               source_note="Low: average car, unknown fuel (4_301_3074_9_1). Base/high: average van up to "
                           "3.5t, diesel (5_303_3102_9_1)."),
    Assumption(id="a6", label="kg to tonnes", low=0.001, base=0.001, high=0.001, unit="t/kg",
               source_note="Unit conversion", judgement_call=True),
]

nodes = [
    Node(id="n1", label="Miles avoided (claimed)", op="input", assumption_id="a1", unit="miles/yr"),
    Node(id="n2", label="Attribution share", op="input", assumption_id="a2", unit="ratio"),
    Node(id="n3", label="Attributable miles avoided", op="multiply", children=["n1", "n2"], unit="miles/yr"),
    Node(id="n4", label="Miles per visit", op="input", assumption_id="a3", unit="miles/visit"),
    Node(id="n5", label="Visits avoided", op="divide", children=["n3", "n4"], unit="visits/yr"),
    Node(id="n6", label="Cost per visit", op="input", assumption_id="a4", unit="GBP/visit"),
    Node(id="n7", label="Customer saving", op="multiply", children=["n5", "n6"], unit="GBP/yr"),
    Node(id="n8", label="Emission factor", op="input", assumption_id="a5", unit="kgCO2e/mile"),
    Node(id="n9", label="kg to t", op="input", assumption_id="a6", unit="t/kg"),
    Node(id="n10", label="Emissions avoided", op="multiply", children=["n3", "n8", "n9"], unit="tCO2e/yr"),
]
tree = DriverTree(root_value_id="n7", root_impact_id="n10", nodes=nodes)
model = ModellerOut(assumptions=assumptions, tree=tree, rationale=(
    "One shared driver, attributable miles avoided, feeds both outputs: divided by miles per visit it gives "
    "visits avoided and the customer saving; multiplied by a UK van factor it gives emissions avoided. "
    "The weakest links are attribution and the cost per visit, both judgement calls. On these assumptions "
    "the customer value case is far larger than the carbon case."))

questions = [
    Question(id="q1", targets_assumption_id="a2", sensitivity_rank=0,
             text="For your largest utility customer, how many field visits per year did they make before and "
                  "after rollout, and what else changed in that period?",
             why_it_matters="Attribution moves both outputs most; a before/after with context would narrow it."),
    Question(id="q2", targets_assumption_id="a4", sensitivity_rank=0,
             text="What do customers tell you a single avoided visit is worth to them, including labour, "
                  "vehicle and rescheduling costs?",
             why_it_matters="Cost per visit drives the whole value case and is currently a guess."),
    Question(id="q3", targets_assumption_id="a3", sensitivity_rank=0,
             text="What is the average round-trip distance per visit in your customers' fleets, and do they "
                  "use vans or cars?",
             why_it_matters="Sets how many visits the claimed miles represent, and which emission factor applies."),
    Question(id="q4", targets_assumption_id="a1", sensitivity_rank=0,
             text="How is the 4 million carbon miles figure calculated, over which customers and which year?",
             why_it_matters="It is the only quantity in the model that comes from the company."),
    Question(id="q5", targets_assumption_id="a5", sensitivity_rank=0,
             text="Could you share the vehicle mix (diesel van, EV, car) for two or three customers?",
             why_it_matters="Switching from diesel vans to cars or EVs cuts the carbon result by a third or more."),
]


def main() -> None:
    page_text = (ROOT / "sources" / "vyntelligence.txt").read_text(encoding="utf-8")
    for c in claims:
        assert quote_in_text(c.quote, page_text), f"quote not found verbatim: {c.quote}"

    ev = evaluate(tree, assumptions)
    ranks = {s.assumption_id: s.rank for s in ev.sensitivity}
    for q in questions:
        q.sensitivity_rank = ranks[q.targets_assumption_id]

    events: list[dict] = []
    t = 0.0

    def emit(type_: str, agent: str | None = None, dt: float = 0.6, **payload) -> None:
        nonlocal t
        t += dt
        events.append({"run_id": "sample-vyntelligence", "seq": len(events), "ts": round(t, 2),
                       "type": type_, "agent": agent, "payload": payload})

    emit("run_started", url=URL, mode="sample", label=LABEL,
         note="Hand-authored sample to show the interface. Not a model run. Numbers are computed by the evaluator.")
    emit("agent_started", "extractor")
    emit("agent_finished", "extractor", dt=2.0, company=COMPANY, page_title="Why We Partnered with Vyntelligence",
         dropped=[])
    for c in claims:
        emit("claim_added", "extractor", claim=c.model_dump())
    for c in claims:
        emit("agent_started", "researcher", claim_id=c.id, dt=0.8)
        for e in evidence:
            if e.claim_id == c.id:
                emit("evidence_added", "researcher", evidence=e.model_dump(), dt=1.2)
        emit("agent_started", "sceptic", claim_id=c.id)
        for o in objections:
            if o.claim_id == c.id:
                emit("objection_added", "sceptic", objection=o.model_dump(), dt=0.9)
        v = next(v for v in verdicts if v.claim_id == c.id)
        emit("verdict_set", "sceptic", verdict=v.model_dump())
    emit("agent_started", "modeller", dt=1.0)
    for a in assumptions:
        emit("assumption_added", "modeller", revision=0, assumption=a.model_dump(), dt=0.4)
    for n in topo(model):
        emit("tree_node_added", "modeller", revision=0, node=n.model_dump(), dt=0.35,
             is_value_root=n.id == tree.root_value_id, is_impact_root=n.id == tree.root_impact_id)
    emit("tree_evaluated", "evaluator", revision=0, tree=tree.model_dump(), evaluation=ev.model_dump(),
         rationale=model.rationale, dt=0.8)
    emit("agent_finished", "modeller")
    emit("agent_started", "questioner")
    for q in sorted(questions, key=lambda q: q.sensitivity_rank):
        emit("question_added", "questioner", revision=0, question=q.model_dump(), dt=0.7)
    emit("agent_finished", "questioner")
    emit("run_finished")

    out = ROOT / "web" / "public" / "replays" / "sample-vyntelligence.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(events)} events)")
    print(f"value  {ev.value.low:,.0f} / {ev.value.base:,.0f} / {ev.value.high:,.0f} GBP/yr")
    print(f"impact {ev.impact.low:,.0f} / {ev.impact.base:,.0f} / {ev.impact.high:,.0f} tCO2e/yr")
    print("sensitivity:", [(s.assumption_id, s.rank) for s in ev.sensitivity])


if __name__ == "__main__":
    main()
