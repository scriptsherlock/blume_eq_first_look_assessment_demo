"""Run store: one JSONL event log per run. The log is also the replay file."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .schema import Event

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)

_LOCKS: dict[str, threading.Lock] = {}


class RunLog:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.path = RUNS_DIR / f"{run_id}.jsonl"
        self._lock = _LOCKS.setdefault(run_id, threading.Lock())

    @property
    def events(self) -> list[dict]:
        return load(self.path) if self.path.exists() else []

    def emit(self, type_: str, agent: str | None = None, **payload) -> dict:
        with self._lock:
            seq = len(self.events)
            ev = Event(run_id=self.run_id, seq=seq, type=type_, agent=agent, payload=payload)
            d = ev.model_dump()
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
            return d


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
