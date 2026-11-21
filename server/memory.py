"""Company memory: retrieval over every earlier assessment.

Each finished run is broken into records (claims with their verdicts and
objections, the final assumptions, the founder questions), embedded, and
stored with the company and date. A new run retrieves:

- history: everything from earlier looks at the same company, so the work
  starts from what is already known instead of a blank page;
- comparables: how the firm sized similar drivers at other companies, so a
  judgement call is anchored in the firm's own past work, not the model's
  general knowledge.

The store is a JSONL file with brute-force cosine search. At the size of a
fund's pipeline (hundreds of companies, thousands of records) that is fast
and needs no vector database.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

STORE = Path(__file__).resolve().parent.parent / "memory" / "store.jsonl"


# ---------------------------------------------------------------- embedders

class LocalEmbedder:
    """Hashed bag of words. Used offline and in tests; weaker than a real embedding model."""
    name = "local-hash@1024"
    dim = 1024
    match_threshold = 0.45

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = np.zeros(self.dim)
            words = re.findall(r"[a-z0-9]+", t.lower())
            for tok in words + [f"{a}_{b}" for a, b in zip(words, words[1:])]:
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0
            v = np.log1p(v)
            n = np.linalg.norm(v) or 1.0
            out.append((v / n).tolist())
        return out


class GeminiEmbedder:
    match_threshold = 0.80

    def __init__(self):
        from . import llm

        self._llm = llm
        self.name = f"{llm.EMBED_MODEL}@{llm.EMBED_DIM}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._llm.embed(texts)


def default_embedder():
    from . import llm

    if os.getenv("EMBEDDER", "gemini").lower() == "local" or not llm.has_key():
        return LocalEmbedder()
    return GeminiEmbedder()


# ---------------------------------------------------------------- unit shape

DIMENSIONLESS = {"", "fraction", "ratio", "%", "percent", "dimensionless", "share", "x", "multiple"}


def norm_unit(unit: str) -> str:
    u = (unit or "").lower().replace(" ", "")
    u = re.sub(r"tonnes?|metrictons?", "t", u)
    return u.replace("kgco2e", "kgco2e").replace("miles", "mile").replace("visits", "visit")


def unit_shape(unit: str) -> tuple:
    """Coarse kind of a unit, so retrieval only compares like with like.

    (currency exponents, is an emission quantity, is dimensionless)
    """
    from .guardrails import unit_currency

    u = (unit or "").strip().lower()
    cur = tuple(sorted(unit_currency(unit).items()))
    return cur, "co2" in u, u in DIMENSIONLESS


def is_conversion(a: dict) -> bool:
    return a["low"] == a["base"] == a["high"] and "conversion" in (a.get("source_note") or "").lower()


# ---------------------------------------------------------------- records

def company_key(name: str) -> str:
    k = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return re.sub(r"(ltd|limited|gmbh|inc|bv|ag|plc|sa)$", "", k)


def same_company(a: str, b: str) -> bool:
    ka, kb = company_key(a), company_key(b)
    if not ka or not kb:
        return False
    return ka == kb or (min(len(ka), len(kb)) >= 3 and (ka.startswith(kb) or kb.startswith(ka)))


@dataclass
class Record:
    id: str
    company: str
    run_id: str
    run_date: str
    source_url: str
    kind: str  # claim | assumption | question
    text: str  # what is embedded
    summary: str  # what a person reads
    data: dict[str, Any] = field(default_factory=dict)
    vector: list[float] = field(default_factory=list)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("vector")
        return d


def _rid(run_id: str, kind: str, local_id: str) -> str:
    return "mem-" + hashlib.sha1(f"{run_id}:{kind}:{local_id}".encode()).hexdigest()[:8]


def _fmt(v: float) -> str:
    return f"{v:,.4g}"


def records_from_events(events: list[dict]) -> list[Record]:
    """Turn one run's event log into memory records (final model revision only)."""
    if not events or events[0]["type"] != "run_started":
        return []
    run_id = events[0]["run_id"]
    url = events[0]["payload"].get("url", "")
    run_date = datetime.fromtimestamp(events[0]["ts"], tz=timezone.utc).date().isoformat() \
        if events[0]["ts"] > 1e9 else events[0]["payload"].get("date", "")
    company = next((e["payload"].get("company") for e in events
                    if e["type"] == "agent_finished" and e.get("agent") == "extractor"), "") or ""
    verdicts = {e["payload"]["verdict"]["claim_id"]: e["payload"]["verdict"] for e in events if e["type"] == "verdict_set"}
    objections: dict[str, list[dict]] = {}
    for e in events:
        if e["type"] == "objection_added":
            o = e["payload"]["objection"]
            objections.setdefault(o["claim_id"], []).append(o)
    rev = max((e["payload"].get("revision", 0) for e in events if e["type"] == "assumption_added"), default=0)

    out: list[Record] = []
    for e in events:
        p = e["payload"]
        if e["type"] == "claim_added":
            c = p["claim"]
            v = verdicts.get(c["id"], {})
            out.append(Record(
                id=_rid(run_id, "claim", c["id"]), company=company, run_id=run_id, run_date=run_date, source_url=url,
                kind="claim", text=c["text"],
                summary=f"{c['text']} ({v.get('status', 'no verdict')})",
                data={"claim": c, "verdict": v, "objections": objections.get(c["id"], [])},
            ))
        elif e["type"] == "assumption_added" and p.get("revision", 0) == rev:
            a = p["assumption"]
            how = "judgement call" if a["judgement_call"] else f"sourced: {a.get('source_note') or a.get('source_url') or ''}"
            out.append(Record(
                id=_rid(run_id, "assumption", a["id"]), company=company, run_id=run_id, run_date=run_date, source_url=url,
                kind="assumption", text=f"{a['label']} [{a['unit']}]",
                summary=f"{a['label']}: {_fmt(a['low'])} – {_fmt(a['base'])} – {_fmt(a['high'])} {a['unit']} ({how})",
                data={"assumption": a},
            ))
        elif e["type"] == "question_added" and p.get("revision", 0) == rev:
            q = p["question"]
            out.append(Record(
                id=_rid(run_id, "question", q["id"]), company=company, run_id=run_id, run_date=run_date, source_url=url,
                kind="question", text=q["text"], summary=q["text"], data={"question": q},
            ))
    return out


# ---------------------------------------------------------------- store

class Memory:
    def __init__(self, path: Path | None = None, embedder=None):
        self.path = path or STORE
        self.embedder = embedder or default_embedder()
        self.records: list[Record] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return
        header = json.loads(lines[0])
        self.records = [Record(**json.loads(line)) for line in lines[1:] if line.strip()]
        if header.get("embedder") != self.embedder.name and self.records:
            self._embed(self.records)  # vectors from another model are not comparable
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"embedder": self.embedder.name}) + "\n")
            for r in self.records:
                f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    def _embed(self, recs: list[Record]) -> None:
        if recs:
            for r, v in zip(recs, self.embedder.embed([r.text for r in recs])):
                r.vector = v

    def has_run(self, run_id: str) -> bool:
        return any(r.run_id == run_id for r in self.records)

    def add_run(self, events: list[dict], replace: bool = True) -> int:
        recs = records_from_events(events)
        if not recs:
            return 0
        run_id = recs[0].run_id
        if replace:
            self.records = [r for r in self.records if r.run_id != run_id]
        elif self.has_run(run_id):
            return 0
        self._embed(recs)
        self.records.extend(recs)
        return len(recs)

    # -- retrieval

    def history(self, company: str, exclude_run: str | None = None) -> list[Record]:
        """Everything from earlier looks at this company, newest run first."""
        recs = [r for r in self.records if same_company(r.company, company) and r.run_id != exclude_run]
        return sorted(recs, key=lambda r: r.run_date, reverse=True)

    def runs(self, company: str, exclude_run: str | None = None) -> list[tuple[str, str]]:
        """(run_id, run_date) of earlier looks, newest first."""
        seen: dict[str, str] = {}
        for r in self.history(company, exclude_run):
            seen.setdefault(r.run_id, r.run_date)
        return sorted(seen.items(), key=lambda x: x[1], reverse=True)

    def search(self, queries: list[str], k: int = 6, kinds: tuple[str, ...] = ("assumption",),
               exclude_company: str | None = None, min_score: float = 0.0,
               unit: str | None = None) -> list[tuple[Record, float]]:
        """Nearest records by meaning. With `unit`, only assumptions whose unit has the same shape
        (money vs money, emission factor vs emission factor, fraction vs fraction) are considered:
        embedding similarity alone rates loosely related drivers too highly."""
        shape = unit_shape(unit) if unit is not None else None
        pool = [r for r in self.records if r.kind in kinds
                and not (exclude_company and same_company(r.company, exclude_company))
                and not (shape is not None and r.kind == "assumption"
                         and unit_shape(r.data["assumption"]["unit"]) != shape)
                and not (r.kind == "assumption" and is_conversion(r.data["assumption"]))]
        if not pool or not queries:
            return []
        q = np.array(self.embedder.embed(queries))
        m = np.array([r.vector for r in pool])
        scores = (q @ m.T).max(axis=0)  # best match against any query
        order = np.argsort(-scores)
        out: list[tuple[Record, float]] = []
        for i in order:
            if scores[i] < min_score or len(out) >= k:
                break
            out.append((pool[i], float(scores[i])))
        return out


# ---------------------------------------------------------------- what changed

def _match(a_texts: list[str], b_texts: list[str], embedder, threshold: float) -> dict[int, tuple[int, float]]:
    """Greedy best match of each a to a distinct b above threshold."""
    if not a_texts or not b_texts:
        return {}
    A, B = np.array(embedder.embed(a_texts)), np.array(embedder.embed(b_texts))
    s = A @ B.T
    pairs = sorted(((s[i, j], i, j) for i in range(len(a_texts)) for j in range(len(b_texts))), reverse=True)
    used_a, used_b, out = set(), set(), {}
    for score, i, j in pairs:
        if score < threshold:
            break
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        out[i] = (j, float(score))
    return out


def _width(a: dict) -> float:
    return (a["high"] - a["low"]) / abs(a["base"]) if a["base"] else math.inf


def diff(previous: list[Record], claims: list[dict], verdicts: dict[str, dict],
         assumptions: list[dict], questions: list[dict], embedder) -> dict:
    """What changed between the latest earlier look and this one. Computed in code, not by the model."""
    if not previous:
        return {}
    last_run = previous[0].run_id
    prev = [r for r in previous if r.run_id == last_run]
    p_claims = [r for r in prev if r.kind == "claim"]
    p_asm = [r for r in prev if r.kind == "assumption"]
    p_qs = [r for r in prev if r.kind == "question"]
    t = embedder.match_threshold

    out: dict[str, Any] = {"previous_run": last_run, "previous_date": prev[0].run_date,
                           "claims": [], "assumptions": [], "questions": []}

    m = _match([c["text"] for c in claims], [r.text for r in p_claims], embedder, t)
    for i, c in enumerate(claims):
        now = verdicts.get(c["id"], {}).get("status")
        if i in m:
            r = p_claims[m[i][0]]
            before = r.data.get("verdict", {}).get("status")
            out["claims"].append({"claim_id": c["id"], "text": c["text"], "change": "verdict changed" if before != now else "seen before",
                                  "before": before, "now": now, "memory_id": r.id})
        else:
            out["claims"].append({"claim_id": c["id"], "text": c["text"], "change": "new", "now": now})
    matched_prev = {j for j, _ in m.values()}
    for j, r in enumerate(p_claims):
        if j not in matched_prev:
            out["claims"].append({"text": r.text, "change": "not repeated", "memory_id": r.id})

    assumptions = [a for a in assumptions if not is_conversion(a)]
    p_asm = [r for r in p_asm if not is_conversion(r.data["assumption"])]
    m = _match([f"{a['label']} [{a['unit']}]" for a in assumptions], [r.text for r in p_asm], embedder, t)
    for i, a in enumerate(assumptions):
        if i not in m:
            out["assumptions"].append({"assumption_id": a["id"], "label": a["label"], "change": "new"})
            continue
        r = p_asm[m[i][0]]
        b = r.data["assumption"]
        wb, wn = _width(b), _width(a)
        if norm_unit(b.get("unit", "")) != norm_unit(a["unit"]):
            change = "redefined"
        elif wn < wb * 0.9:
            change = "narrowed"
        elif wn > wb * 1.1:
            change = "widened"
        elif abs(a["base"] - b["base"]) > 0.05 * abs(b["base"] or 1):
            change = "base moved"
        else:
            change = "unchanged"
        out["assumptions"].append({
            "assumption_id": a["id"], "label": a["label"], "change": change, "memory_id": r.id,
            "before": {k: b[k] for k in ("low", "base", "high", "unit")},
            "now": {k: a[k] for k in ("low", "base", "high", "unit")},
            "became_sourced": bool(b.get("judgement_call")) and not a["judgement_call"],
        })

    m = _match([q["text"] for q in questions], [r.text for r in p_qs], embedder, t * 0.95)
    asked_again = {j for j, _ in m.values()}
    for j, r in enumerate(p_qs):
        out["questions"].append({"text": r.text, "memory_id": r.id,
                                 "status": "still open" if j in asked_again else "not asked again"})
    return out
