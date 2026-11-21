"""Company memory: ingestion, retrieval, history, and what changed since the last look."""
import copy
import json
from pathlib import Path

from server.memory import LocalEmbedder, Memory, diff, records_from_events, same_company

ROOT = Path(__file__).resolve().parents[1]
REPLAYS = ROOT / "web" / "public" / "replays"


def events(name):
    return [json.loads(l) for l in (REPLAYS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def mem(tmp_path):
    return Memory(tmp_path / "store.jsonl", embedder=LocalEmbedder())


def test_records_cover_claims_assumptions_and_questions():
    recs = records_from_events(events("vyntelligence"))
    kinds = {r.kind for r in recs}
    assert kinds == {"claim", "assumption", "question"}
    assert all(r.company == "Vyntelligence" and r.run_date for r in recs)
    claim = next(r for r in recs if r.kind == "claim")
    assert "verdict" in claim.data and claim.summary.endswith(")")


def test_company_matching_tolerates_short_names():
    assert same_company("Vyntelligence", "Vyn")
    assert same_company("SPARETECH GmbH", "Sparetech")
    assert not same_company("CameraMatics", "Vyntelligence")
    assert not same_company("", "Vyn")


def test_add_run_is_idempotent_and_persists(tmp_path):
    m = mem(tmp_path)
    n = m.add_run(events("vyntelligence"))
    assert n > 0
    m.add_run(events("vyntelligence"))  # same run again replaces, not duplicates
    assert len(m.records) == n
    m.save()
    again = Memory(tmp_path / "store.jsonl", embedder=LocalEmbedder())
    assert len(again.records) == n and len(again.records[0].vector) == LocalEmbedder.dim


def test_history_returns_only_that_company(tmp_path):
    m = mem(tmp_path)
    for name in ("vyntelligence", "cameramatics", "sparetech"):
        m.add_run(events(name))
    hist = m.history("Vyn")
    assert hist and all(r.company == "Vyntelligence" for r in hist)
    assert len(m.runs("Vyntelligence")) == 1
    assert m.runs("Unknown Co") == []


def test_comparables_come_from_other_companies(tmp_path):
    m = mem(tmp_path)
    for name in ("vyntelligence", "cameramatics", "sparetech"):
        m.add_run(events(name))
    hits = m.search(["Emission factor per vehicle mile [kgCO2e/mile]"], k=3, exclude_company="Vyntelligence")
    assert hits
    assert all(r.company != "Vyntelligence" and r.kind == "assumption" for r, _ in hits)
    assert hits[0][1] >= hits[-1][1]


def test_diff_reports_narrowed_ranges_and_open_questions(tmp_path):
    m = mem(tmp_path)
    first = events("vyntelligence")
    m.add_run(first)
    prev = m.history("Vyntelligence")

    # A second look: same claims, one assumption narrowed, one question asked again.
    rev = max(e["payload"].get("revision", 0) for e in first if e["type"] == "assumption_added")
    claims = [e["payload"]["claim"] for e in first if e["type"] == "claim_added"]
    verdicts = {e["payload"]["verdict"]["claim_id"]: e["payload"]["verdict"] for e in first if e["type"] == "verdict_set"}
    verdicts[claims[0]["id"]] = {**verdicts[claims[0]["id"]], "status": "supported"}
    asm = [copy.deepcopy(e["payload"]["assumption"]) for e in first
           if e["type"] == "assumption_added" and e["payload"].get("revision", 0) == rev]
    target = next(a for a in asm if a["high"] > a["low"])
    target["low"], target["high"] = target["base"] * 0.95, target["base"] * 1.05
    qs = [e["payload"]["question"] for e in first if e["type"] == "question_added"][:1]

    d = diff(prev, claims, verdicts, asm, qs, m.embedder)
    assert d["previous_run"] == first[0]["run_id"]
    changed = {a["assumption_id"]: a["change"] for a in d["assumptions"]}
    assert changed[target["id"]] == "narrowed"
    assert any(c["change"] == "verdict changed" for c in d["claims"])
    statuses = [q["status"] for q in d["questions"]]
    assert "still open" in statuses and "not asked again" in statuses


def test_diff_is_empty_on_a_first_look(tmp_path):
    assert diff([], [], {}, [], [], LocalEmbedder()) == {}


def test_store_reembeds_when_the_embedder_changes(tmp_path):
    m = mem(tmp_path)
    m.add_run(events("cameramatics"))
    m.save()

    class Other(LocalEmbedder):
        name = "other@8"
        dim = 8

    reloaded = Memory(tmp_path / "store.jsonl", embedder=Other())
    assert len(reloaded.records[0].vector) == 8


def test_unit_filter_keeps_like_with_like(tmp_path):
    from server.memory import unit_shape
    assert unit_shape("GBP/visit") == unit_shape("GBP/mile")
    assert unit_shape("GBP/visit") != unit_shape("fraction")
    assert unit_shape("kg CO2e/mile") != unit_shape("miles/visit")
    m = mem(tmp_path)
    for name in ("cameramatics", "sparetech"):
        m.add_run(events(name))
    hits = m.search(["Average miles per physical field visit [miles/visit]"], k=10, unit="miles/visit")
    units = {r.data["assumption"]["unit"] for r, _ in hits}
    assert not any("co2" in u.lower() or "gbp" in u.lower() for u in units)


def test_diff_ignores_unit_spelling_and_conversions(tmp_path):
    m = mem(tmp_path)
    first = events("vyntelligence")
    m.add_run(first)
    rev = max(e["payload"].get("revision", 0) for e in first if e["type"] == "assumption_added")
    asm = [copy.deepcopy(e["payload"]["assumption"]) for e in first
           if e["type"] == "assumption_added" and e["payload"].get("revision", 0) == rev]
    for a in asm:
        a["unit"] = a["unit"].replace("tonnes", "t").replace(" ", "")
    d = diff(m.history("Vyntelligence"), [], {}, asm, [], m.embedder)
    assert not [a for a in d["assumptions"] if a["change"] == "redefined"]
    assert not [a for a in d["assumptions"] if "kilograms to tonnes" in a["label"].lower()]
