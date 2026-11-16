"""End-to-end run of the orchestrator with the model stubbed out.

Checks the wiring (fetch -> agents -> evaluator -> events) without a key.
Does not test prompt quality; that needs live runs.
"""
from pathlib import Path

import pytest

from server import llm, orchestrator, store
from server.agents import extractor, modeller, questioner, researcher, sceptic
from server.schema import (
    Assumption, Claim, DriverTree, EvidenceItem, ExtractorOut, ModellerOut, Node, Objection,
    Question, QuestionerOut, ResearcherOut, ScepticOut, Verdict,
)

ROOT = Path(__file__).resolve().parents[1]
URL = "https://example.com/vyntelligence"


def fake_json(prompt, schema, model=None, system=None):
    if schema is ExtractorOut:
        return ExtractorOut(company="Vyntelligence", claims=[
            Claim(id="c1", kind="impact", text="4M miles", quote="saves approximately 4 million carbon miles annually"),
            Claim(id="c2", kind="value", text="invented", quote="this sentence is not on the page at all"),
        ])
    if schema is ResearcherOut:
        return ResearcherOut(items=[EvidenceItem(stance="context", summary="factor table", source_index=0),
                                    EvidenceItem(stance="supports", summary="hallucinated", source_index=7)])
    if schema is ScepticOut:
        return ScepticOut(
            objections=[Objection(id="o1", claim_id="?", text="undefined unit", severity=3, what_would_resolve_it="data")],
            verdict=Verdict(claim_id="?", status="needs evidence", reason="one source"))
    if schema is ModellerOut:
        return ModellerOut(rationale="r", assumptions=[
            Assumption(id="a1", label="miles", low=3e6, base=4e6, high=4.5e6, unit="miles/yr", source_url=URL, claim_ids=["c1"]),
            Assumption(id="a2", label="cost per mile", low=0.5, base=1, high=2, unit="GBP/mile", judgement_call=True),
            Assumption(id="a3", label="factor", low=0.0003, base=0.0004, high=0.0004, unit="t/mile", judgement_call=True),
        ], tree=DriverTree(root_value_id="v", root_impact_id="i", nodes=[
            Node(id="n1", label="miles", op="input", assumption_id="a1"),
            Node(id="n2", label="cost", op="input", assumption_id="a2"),
            Node(id="n3", label="factor", op="input", assumption_id="a3"),
            Node(id="v", label="value", op="multiply", children=["n1", "n2"], unit="GBP/yr"),
            Node(id="i", label="impact", op="multiply", children=["n1", "n3"], unit="tCO2e/yr"),
        ]))
    if schema is QuestionerOut:
        return QuestionerOut(questions=[
            Question(id="q1", text="How measured?", targets_assumption_id="a1", sensitivity_rank=0, why_it_matters="x"),
            Question(id="q2", text="Ghost?", targets_assumption_id="zzz", sensitivity_rank=0, why_it_matters="x"),
        ])
    raise AssertionError(schema)


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    page = ("Vyntelligence", (ROOT / "sources" / "vyntelligence.txt").read_text(encoding="utf-8"))
    monkeypatch.setattr(llm, "generate_json", fake_json)
    monkeypatch.setattr(llm, "generate_grounded",
                        lambda *a, **k: ("report", [llm.Source(url="https://gov.uk/factors", title="gov.uk")]))
    monkeypatch.setattr(orchestrator, "fetch", lambda url: page)
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path)


def test_full_run_emits_expected_events(stubbed):
    orchestrator.run("abc1234567", URL)
    evs = store.RunLog("abc1234567").events
    types = [e["type"] for e in evs]
    assert types[0] == "run_started" and types[-1] == "run_finished", evs[-1]

    claims = [e["payload"]["claim"] for e in evs if e["type"] == "claim_added"]
    assert [c["id"] for c in claims] == ["c1"]  # invented quote dropped
    dropped = next(e for e in evs if e["type"] == "agent_finished" and e["agent"] == "extractor")["payload"]["dropped"]
    assert len(dropped) == 1

    evidence = [e["payload"]["evidence"] for e in evs if e["type"] == "evidence_added"]
    assert len(evidence) == 1  # source_index 7 was not returned by grounding, so it is dropped
    assert evidence[0]["url"] == "https://gov.uk/factors"

    verdict = next(e for e in evs if e["type"] == "verdict_set")["payload"]["verdict"]
    assert verdict["claim_id"] == "c1"

    ev = next(e for e in evs if e["type"] == "tree_evaluated")["payload"]["evaluation"]
    assert ev["value"]["base"] == pytest.approx(4e6)
    assert ev["impact"]["base"] == pytest.approx(1600)

    qs = [e["payload"]["question"] for e in evs if e["type"] == "question_added"]
    assert [q["id"] for q in qs] == ["q1"]  # question targeting an unknown assumption dropped
    assert qs[0]["sensitivity_rank"] >= 1


def test_whatif_bumps_revision(stubbed):
    orchestrator.run("abc1234568", URL)
    orchestrator.whatif("abc1234568", "halve the cost per mile")
    evs = store.RunLog("abc1234568").events
    revs = {e["payload"].get("revision") for e in evs if e["type"] == "tree_evaluated"}
    assert revs == {0, 1}


def test_whatif_on_unknown_run_reports_error(stubbed):
    orchestrator.whatif("ffffffffff", "anything")
    assert store.RunLog("ffffffffff").events[-1]["type"] == "error"
