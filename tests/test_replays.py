"""Checks every saved replay without an API key (plan section 12)."""
import json
from pathlib import Path

import pytest

from server.evaluator import evaluate
from server.fetch import quote_in_text
from server.schema import Assumption, DriverTree, Evaluation

ROOT = Path(__file__).resolve().parents[1]
REPLAYS = sorted((ROOT / "web" / "public" / "replays").glob("*.jsonl"))
SOURCES = ROOT / "sources"


def events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def of(evs, type_):
    return [e["payload"] for e in evs if e["type"] == type_]


def last_revision(evs, type_, key):
    rev = max((p.get("revision", 0) for p in of(evs, type_)), default=0)
    return [p[key] for p in of(evs, type_) if p.get("revision", 0) == rev]


def saved_source(url):
    """Find the saved copy of a source page by its slug."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    for f in SOURCES.glob("*.txt"):
        text = f.read_text(encoding="utf-8")
        if slug and text.startswith(f"URL: {url}"):
            return text
    return None


def test_there_is_at_least_one_replay():
    assert REPLAYS


def test_index_lists_only_existing_files():
    index = json.loads((ROOT / "web" / "public" / "replays" / "index.json").read_text(encoding="utf-8"))
    names = {p.name for p in REPLAYS}
    assert all(item["file"] in names for item in index)


@pytest.mark.parametrize("path", REPLAYS, ids=lambda p: p.stem)
class TestReplay:
    def test_parses_and_finishes(self, path):
        evs = events(path)
        assert evs[0]["type"] == "run_started"
        assert evs[-1]["type"] == "run_finished"
        assert [e["seq"] for e in evs] == list(range(len(evs)))
        assert "Illustrative" in evs[0]["payload"]["label"]

    def test_quotes_are_verbatim(self, path):
        evs = events(path)
        claims = [p["claim"] for p in of(evs, "claim_added")]
        assert claims
        for c in claims:
            text = saved_source(c["source_url"])
            if text is None:
                pytest.skip(f"no saved source for {c['source_url']}")
            assert quote_in_text(c["quote"], text), c["quote"]

    def test_assumptions_sourced_or_flagged_and_ordered(self, path):
        for a in last_revision(events(path), "assumption_added", "assumption"):
            assert a["source_url"] or a["judgement_call"], a["id"]
            assert a["low"] <= a["base"] <= a["high"], a["id"]

    def test_recorded_evaluation_matches_evaluator(self, path):
        evs = events(path)
        rec = of(evs, "tree_evaluated")[-1]
        tree = DriverTree.model_validate(rec["tree"])
        assumptions = [Assumption.model_validate(a) for a in last_revision(evs, "assumption_added", "assumption")]
        recorded = Evaluation.model_validate(rec["evaluation"])
        fresh = evaluate(tree, assumptions)
        for root in ("value", "impact"):
            r, f = getattr(recorded, root), getattr(fresh, root)
            assert (r.low, r.base, r.high) == pytest.approx((f.low, f.base, f.high))
            assert r.low <= r.base <= r.high

    def test_questions_target_real_assumptions(self, path):
        evs = events(path)
        ids = {a["id"] for a in last_revision(evs, "assumption_added", "assumption")}
        qs = last_revision(evs, "question_added", "question")
        assert 1 <= len(qs) <= 5
        assert all(q["targets_assumption_id"] in ids for q in qs)

    def test_evidence_and_verdicts_reference_claims(self, path):
        evs = events(path)
        ids = {p["claim"]["id"] for p in of(evs, "claim_added")}
        assert all(p["evidence"]["claim_id"] in ids for p in of(evs, "evidence_added"))
        assert all(p["objection"]["claim_id"] in ids for p in of(evs, "objection_added"))
        assert {p["verdict"]["claim_id"] for p in of(evs, "verdict_set")} <= ids


@pytest.mark.parametrize("path", REPLAYS, ids=lambda p: p.stem)
def test_final_model_passes_guardrails(path):
    """Currency, emission-factor and exchange-rate rules hold for every published run."""
    from server import references
    from server.agents import modeller
    from server.schema import Claim, ModellerOut

    evs = events(path)
    rec = of(evs, "tree_evaluated")[-1]
    out = ModellerOut(
        assumptions=[Assumption.model_validate(a) for a in last_revision(evs, "assumption_added", "assumption")],
        tree=DriverTree.model_validate(rec["tree"]),
        rationale=rec.get("rationale", ""),
    )
    claims = [Claim.model_validate(p["claim"]) for p in of(evs, "claim_added")]
    assert modeller.problems(out, references.load(live_fx=False), claims) == []


@pytest.mark.parametrize("path", REPLAYS, ids=lambda p: p.stem)
def test_memory_citations_point_at_recalled_memories(path):
    """Every [mem-...] an assumption cites was actually retrieved and shown in that run."""
    import re
    evs = events(path)
    recalled = {p["record"]["id"] for p in of(evs, "memory_recalled")}
    for a in last_revision(evs, "assumption_added", "assumption"):
        for mid in re.findall(r"mem-[0-9a-f]{8}", a.get("source_note") or ""):
            assert mid in recalled, f"{a['id']} cites {mid}, which was not recalled"
