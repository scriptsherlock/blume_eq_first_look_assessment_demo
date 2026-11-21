"""Rebuild company memory from saved runs.

Usage:
    .venv/Scripts/python -m scripts.rebuild_memory            # every replay in web/public/replays
    .venv/Scripts/python -m scripts.rebuild_memory a.jsonl b.jsonl

Runs are added oldest first, so "earlier look" means what it says.
Uses Gemini embeddings when a key is set, else the local embedder (EMBEDDER=local forces it).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import memory  # noqa: E402

REPLAYS = ROOT / "web" / "public" / "replays"


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main(paths: list[str]) -> None:
    files = [Path(p) for p in paths] if paths else sorted(REPLAYS.glob("*.jsonl"))
    runs = sorted((load(f) for f in files), key=lambda evs: evs[0]["ts"])
    if memory.STORE.exists():
        memory.STORE.unlink()
    m = memory.Memory()
    for evs in runs:
        n = m.add_run(evs)
        company = next((e["payload"].get("company") for e in evs if e["type"] == "agent_finished"
                        and e.get("agent") == "extractor"), "?")
        print(f"{company:20s} {evs[0]['run_id']}  {n} records")
    m.save()
    print(f"memory: {len(m.records)} records, embedder {m.embedder.name}, at {memory.STORE}")


if __name__ == "__main__":
    main(sys.argv[1:])
