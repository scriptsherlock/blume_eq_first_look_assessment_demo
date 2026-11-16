"""FastAPI server: start runs, stream events over SSE, apply what-ifs.

Run from the repo root:
    .venv/Scripts/python -m uvicorn server.main:app --reload
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import llm, orchestrator
from .store import RunLog

app = FastAPI(title="Evidence Map")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunIn(BaseModel):
    url: str


class WhatIfIn(BaseModel):
    instruction: str


def _check_id(run_id: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{10}", run_id):
        raise HTTPException(404, "unknown run")


@app.get("/health")
def health():
    return {"ok": True, "live": llm.has_key(), "model_fast": llm.MODEL_FAST, "model_strong": llm.MODEL_STRONG}


@app.post("/runs")
def start(body: RunIn):
    if not llm.has_key():
        raise HTTPException(400, "GEMINI_API_KEY is not set on the server.")
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http:// or https://")
    run_id = uuid.uuid4().hex[:10]
    threading.Thread(target=orchestrator.run, args=(run_id, body.url), daemon=True).start()
    return {"run_id": run_id}


@app.post("/runs/{run_id}/whatif")
def whatif(run_id: str, body: WhatIfIn):
    _check_id(run_id)
    threading.Thread(target=orchestrator.whatif, args=(run_id, body.instruction), daemon=True).start()
    return {"ok": True}


@app.get("/runs/{run_id}/events")
async def events(run_id: str, since: int = 0):
    _check_id(run_id)

    async def stream():
        sent, idle = since, 0
        while True:
            new = RunLog(run_id).events[sent:]
            for ev in new:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            sent += len(new)
            idle = 0 if new else idle + 1
            if new and new[-1]["type"] in ("run_finished", "error"):
                break
            if idle > 1200:  # ~10 minutes with nothing new
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")
