"""End-to-end run of the orchestrator with the model stubbed out.

Checks the wiring (fetch -> agents -> evaluator -> events) without a key.
Does not test prompt quality; that needs live runs.
"""
from pathlib import Path

import pytest

from server import llm, orchestrator, references, search, store
from server.agents import extractor, modeller, questioner, researcher, sceptic
from server.schema import (
    Assumption, Claim, DriverTree, EvidenceItem, ExtractorOut, ModellerOut, Node, Objection,
    Question, QuestionerOut, ResearcherOut, ScepticOut, SearchPlan, Verdict,
)

FACTOR_PAGE = "UK conversion factors. An average diesel van emits 0.41 kg CO2e per mile driven. " * 10

ROOT = Path(__file__).resolve().parents[1]
URL = "https://example.com/vyntelligence"


def fake_json(prompt, schema, model=None, system=None):
    if schema is ExtractorOut:
        return ExtractorOut(company="Vyntelligence", claims=[
            Claim(id="c1", kind="impact", text="4M miles", quote="saves approximately 4 million carbon miles annually"),
            Claim(id="c2", kind="value", text="invented", quote="this sentence is not on the page at all"),
        ])
    if schema is SearchPlan:
        return SearchPlan(queries=["van emissions per mile UK"])
    if schema is ResearcherOut:
        return ResearcherOut(items=[
            EvidenceItem(stance="context", summary="factor table", source_index=0,
                         quote="An average diesel van emits 0.41 kg CO2e per mile driven."),
            EvidenceItem(stance="supports", summary="quote not on page", source_index=0, quote="Vans emit nothing at all."),
            EvidenceItem(stance="supports", summary="hallucinated page", source_index=7, quote="x" * 20),
        ])
    if schema is ScepticOut:
        return ScepticOut(
            objections=[Objection(id="o1", claim_id="?", text="undefined unit", severity=3, what_would_resolve_it="data")],
            verdict=Verdict(claim_id="?", status="needs evidence", reason="one source"))
    if schema is ModellerOut:
        return ModellerOut(rationale="r", assumptions=[
            Assumption(id="a1", label="miles", low=3e6, base=4e6, high=4.5e6, unit="miles/yr", source_url=URL, claim_ids=["c1"]),
            Assumption(id="a2", label="cost per mile", low=0.5, base=1, high=2, unit="GBP/mile", judgement_call=True),
            Assumption(id="a3", label="van factor", low=0.00026915, base=0.00041138, high=0.00041138, unit="tCO2e/mile",
                       source_note="[5_303_3102_9_1] van, diesel"),
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
    monkeypatch.setenv("SEARCH_PROVIDER", "web")
    monkeypatch.setattr(search, "web_search", lambda q, k=5: [
        search.Hit(url="https://www.vyntelligence.com/blog", title="Our own blog", snippet=""),  # not independent
        search.Hit(url="https://gov.uk/factors", title="UK factors", snippet=""),
    ])
    monkeypatch.setattr(search, "read_page", lambda url: FACTOR_PAGE)
    monkeypatch.setattr(orchestrator, "fetch", lambda url: page)
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path)
    offline = references.load(live_fx=False)
    monkeypatch.setattr(references, "load", lambda live_fx=True: offline)


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
    assert len(evidence) == 1  # own-site page excluded; quote not on page and made-up page index both dropped
    assert evidence[0]["quote"].startswith("An average diesel van")
    assert evidence[0]["url"] == "https://gov.uk/factors"

    verdict = next(e for e in evs if e["type"] == "verdict_set")["payload"]["verdict"]
    assert verdict["claim_id"] == "c1"

    ev = next(e for e in evs if e["type"] == "tree_evaluated")["payload"]["evaluation"]
    assert ev["value"]["base"] == pytest.approx(4e6)
    assert ev["impact"]["base"] == pytest.approx(4e6 * 0.00041138)

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


def test_run_continues_when_search_is_unavailable(stubbed, monkeypatch):
    def no_search(*a, **k):
        raise RuntimeError("rate limited")
    monkeypatch.setattr(search, "web_search", no_search)
    orchestrator.run("abc1234569", URL)
    evs = store.RunLog("abc1234569").events
    assert evs[-1]["type"] == "run_finished"
    assert not [e for e in evs if e["type"] == "evidence_added"]
    notes = [e["payload"].get("note") for e in evs if e["type"] == "agent_finished" and e["agent"] == "researcher"]
    assert notes and "unavailable" in notes[0]  # given up after two failures, not one
    assert [e for e in evs if e["type"] == "verdict_set"]


def test_modeller_rejects_trees_without_a_shared_driver():
    from server.evaluator import TreeError
    out = fake_json("", ModellerOut)
    modeller.check(out, references.load(live_fx=False), [])  # shares n1
    out.tree.nodes[4].children = ["n3", "n3"]  # impact no longer uses miles
    with pytest.raises(TreeError, match="share no input"):
        modeller.check(out, references.load(live_fx=False), [])


def test_second_look_recalls_history_finds_comparables_and_reports_changes(stubbed, monkeypatch):
    import json as _json
    from server import memory as memory_mod

    replays = ROOT / "web" / "public" / "replays"
    seed = memory_mod.Memory()
    for name in ("vyntelligence", "cameramatics"):
        seed.add_run([_json.loads(l) for l in (replays / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if l])
    seed.save()

    calls = []
    real_anchor = modeller.anchor
    monkeypatch.setattr(modeller, "anchor", lambda *a, **k: calls.append(a[1]) or real_anchor(*a, **k))

    orchestrator.run("abc1234570", URL)
    evs = store.RunLog("abc1234570").events
    assert evs[-1]["type"] == "run_finished", evs[-1]

    recalled = [e["payload"] for e in evs if e["type"] == "memory_recalled"]
    roles = {p["role"] for p in recalled}
    assert "history" in roles
    assert all(p["record"]["company"] == "Vyntelligence" for p in recalled if p["role"] == "history")
    assert all(p["record"]["company"] != "Vyntelligence" for p in recalled if p["role"] == "comparable")

    # "cost per mile [GBP/mile]" should find CameraMatics' per-mile savings, and trigger the anchoring pass
    comps = [p for p in recalled if p["role"] == "comparable"]
    assert any(p["record"]["company"] == "CameraMatics" and "per mile" in p["record"]["text"] for p in comps)
    assert calls and "[mem-" in calls[0]

    d = next(e["payload"]["diff"] for e in evs if e["type"] == "memory_diff")
    assert d["claims"] and d["questions"]

    after = memory_mod.Memory()
    assert after.has_run("abc1234570")  # the next look will start from this one


def test_first_look_has_no_diff_and_is_remembered(stubbed):
    from server import memory as memory_mod

    orchestrator.run("abc1234571", URL)
    evs = store.RunLog("abc1234571").events
    assert not [e for e in evs if e["type"] == "memory_diff"]
    assert not [e for e in evs if e["type"] == "memory_recalled" and e["payload"]["role"] == "history"]
    assert memory_mod.Memory().has_run("abc1234571")


def test_modeller_rejects_made_up_memory_ids():
    out = fake_json("", ModellerOut)
    out.assumptions[1].source_note = "[mem-deadbeef] as before"
    found = modeller.problems(out, references.load(live_fx=False), [], memory={"mem-00000000": None})
    assert any("mem-deadbeef" in f for f in found)



def test_citing_an_earlier_sourced_value_restores_its_source():
    from server.memory import Record
    out = fake_json("", ModellerOut)
    a = out.assumptions[0]
    a.source_url, a.claim_ids, a.judgement_call = None, [], False  # the model forgot the source
    a.source_note = "[mem-11111111] same as last look"
    prev = Record(id="mem-11111111", company="Vyntelligence", run_id="r0", run_date="2026-11-16", source_url=URL,
                  kind="assumption", text="miles", summary="miles",
                  data={"assumption": {**a.model_dump(), "source_url": URL, "judgement_call": False}})
    found = modeller.problems(out, references.load(live_fx=False), [], memory={"mem-11111111": prev})
    assert found == []
    assert a.source_url == URL and not a.judgement_call


def test_one_busy_call_does_not_end_the_run(stubbed, monkeypatch):
    calls = {"n": 0}
    real = sceptic.run

    def flaky(*a, **k):
        calls["n"] += 1
        raise RuntimeError("503 UNAVAILABLE high demand")
    monkeypatch.setattr(sceptic, "run", flaky)
    orchestrator.run("abc1234572", URL)
    evs = store.RunLog("abc1234572").events
    assert evs[-1]["type"] == "run_finished"  # model and questions still produced
    notes = [e["payload"].get("note", "") for e in evs if e["type"] == "agent_finished"]
    assert any("Couldn't argue against" in n and "busy" in n for n in notes)
    assert [e for e in evs if e["type"] == "question_added"]
