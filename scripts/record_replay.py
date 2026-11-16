"""Record a live run as a replay file for the static demo.

Usage (needs GEMINI_API_KEY in .env):
    .venv/Scripts/python -m scripts.record_replay <url> <name>

Writes web/public/replays/<name>.jsonl and adds it to the replay index.
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import orchestrator  # noqa: E402
from server.store import RUNS_DIR, load  # noqa: E402

REPLAYS = ROOT / "web" / "public" / "replays"


def main(url: str, name: str) -> None:
    run_id = uuid.uuid4().hex[:10]
    print(f"running {url} as {run_id} ...")
    orchestrator.run(run_id, url)
    src = RUNS_DIR / f"{run_id}.jsonl"
    events = load(src)
    last = events[-1]
    if last["type"] == "error":
        print("run failed:", last["payload"].get("message"))
        sys.exit(1)
    REPLAYS.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, REPLAYS / f"{name}.jsonl")
    print(f"saved {REPLAYS / f'{name}.jsonl'} ({len(events)} events)")
    print("add it to web/public/replays/index.json to show it on the start screen")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
