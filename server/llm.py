"""The provider seam. Every model call in the app goes through this file.

Runs on Gemini (google-genai). To switch to Claude, reimplement
generate_json() and generate_grounded() here; nothing else changes.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

T = TypeVar("T", bound=BaseModel)

# Model IDs come from the environment. Check current IDs in Google AI Studio.
MODEL_FAST = os.getenv("MODEL_FAST", "gemini-2.5-flash")
MODEL_STRONG = os.getenv("MODEL_STRONG", "gemini-2.5-pro")
CALL_DELAY_S = float(os.getenv("CALL_DELAY_S", "1.0"))

_client = None


def client():
    global _client
    if _client is None:
        from google import genai

        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and add a key.")
        _client = genai.Client(api_key=key)
    return _client


def has_key() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


@dataclass
class Source:
    url: str
    title: str


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def generate_json(prompt: str, schema: type[T], model: str | None = None, system: str | None = None) -> T:
    """Ask for JSON matching `schema`. Retries once with the validation error appended."""
    from google.genai import types

    model = model or MODEL_FAST
    attempt_prompt = prompt
    last_err: Exception | None = None
    for _ in range(2):
        time.sleep(CALL_DELAY_S)
        resp = client().models.generate_content(
            model=model,
            contents=attempt_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=schema.model_json_schema(),
                temperature=0.4,
            ),
        )
        try:
            return schema.model_validate(json.loads(_strip_fences(resp.text or "")))
        except (ValidationError, json.JSONDecodeError) as e:
            last_err = e
            attempt_prompt = (
                f"{prompt}\n\nYour previous answer failed validation with this error:\n{e}\n"
                "Return corrected JSON only."
            )
    raise RuntimeError(f"Model output failed validation twice: {last_err}")


def generate_grounded(prompt: str, model: str | None = None, system: str | None = None) -> tuple[str, list[Source]]:
    """Ask with Google Search grounding. Returns prose and the sources Gemini actually used.

    Source URLs come from grounding metadata, never from the model's text.
    """
    from google.genai import types

    time.sleep(CALL_DELAY_S)
    resp = client().models.generate_content(
        model=model or MODEL_FAST,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.3,
        ),
    )
    sources: list[Source] = []
    seen: set[str] = set()
    for cand in resp.candidates or []:
        meta = getattr(cand, "grounding_metadata", None)
        for chunk in (getattr(meta, "grounding_chunks", None) or []):
            web = getattr(chunk, "web", None)
            if web and web.uri and web.uri not in seen:
                seen.add(web.uri)
                sources.append(Source(url=web.uri, title=web.title or web.domain or ""))
    return resp.text or "", sources
