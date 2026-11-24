"""Record a live run as a replay file for the static demo.

Usage (needs GEMINI_API_KEY in .env):
    .venv/Scripts/python -m scripts.record_replay <url> <name>
    .venv/Scripts/python -m scripts.record_replay --resume <run_id> <name>

--resume finishes a run that stopped at the model step (usually "Gemini is busy")
without redoing the reading, searching and arguing.

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


def main(url: str, name: str, resume_from: str | None = None) -> None:
    run_id = uuid.uuid4().hex[:10]
    if resume_from:
        print(f"resuming {resume_from} as {run_id} ...")
        orchestrator.resume(run_id, resume_from)
    else:
        print(f"running {url} as {run_id} ...")
        orchestrator.run(run_id, url)
    src = RUNS_DIR / f"{run_id}.jsonl"
    events = load(src)
    last = events[-1]
    if last["type"] == "error":
        print("run failed:", last["payload"].get("message"))
        sys.exit(1)
    claims = {e["payload"]["claim"]["id"] for e in events if e["type"] == "claim_added"}
    judged = {e["payload"]["verdict"]["claim_id"] for e in events if e["type"] == "verdict_set"}
    questions = [e for e in events if e["type"] == "question_added"]
    if claims - judged or not questions:
        print(f"run incomplete (verdicts {len(judged)}/{len(claims)}, questions {len(questions)}); not saved as a replay")
        sys.exit(1)
    REPLAYS.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, REPLAYS / f"{name}.jsonl")
    print(f"saved {REPLAYS / f'{name}.jsonl'} ({len(events)} events)")
    print("add it to web/public/replays/index.json to show it on the start screen")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "--resume":
        main("", args[2], resume_from=args[1])
    elif len(args) == 2:
        main(args[0], args[1])
    else:
        print(__doc__)
        sys.exit(2)
