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
# Set SEARCH=off to skip Google Search grounding (e.g. on API tiers without search quota).
SEARCH_ENABLED = os.getenv("SEARCH", "on").lower() not in ("off", "0", "false")
RATE_LIMIT_RETRIES = 3
# Used only when the main model stays overloaded (503) after retries.
MODEL_FALLBACK = os.getenv("MODEL_FALLBACK", "")
FALLBACK_USED: list[str] = []  # model ids actually used as fallback, for the run log


class SearchUnavailable(RuntimeError):
    """Google Search grounding is not available for this key or model."""

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


def _is_quota(e: Exception) -> bool:
    return getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e)


def _is_transient(e: Exception) -> bool:
    return _is_quota(e) or getattr(e, "code", None) in (500, 503) or "UNAVAILABLE" in str(e)


def _call(**kw):
    """generate_content with backoff on rate limits (429) and temporary overload (500/503)."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        time.sleep(CALL_DELAY_S)
        try:
            return client().models.generate_content(**kw)
        except Exception as e:
            if not _is_transient(e):
                raise
            if attempt == RATE_LIMIT_RETRIES:
                overloaded = not _is_quota(e)
                if overloaded and MODEL_FALLBACK and kw.get("model") != MODEL_FALLBACK:
                    FALLBACK_USED.append(MODEL_FALLBACK)
                    return _call(**{**kw, "model": MODEL_FALLBACK})
                raise
            time.sleep(15 * (attempt + 1))


def generate_json(prompt: str, schema: type[T], model: str | None = None, system: str | None = None) -> T:
    """Ask for JSON matching `schema`. Retries once with the validation error appended."""
    from google.genai import types

    model = model or MODEL_FAST
    attempt_prompt = prompt
    last_err: Exception | None = None
    for _ in range(2):
        resp = _call(
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

    if not SEARCH_ENABLED:
        raise SearchUnavailable("search is turned off (SEARCH=off)")
    try:
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
    except Exception as e:
        # Free tiers often have no Google Search quota; one retry separates that from a per-minute limit.
        if not _is_quota(e):
            raise
        time.sleep(30)
        try:
            resp = client().models.generate_content(
                model=model or MODEL_FAST,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.3,
                ),
            )
        except Exception as e2:
            if _is_quota(e2):
                raise SearchUnavailable("Google Search grounding has no quota on this API key") from e2
            raise
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


# ---------------------------------------------------------------- embeddings

EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = 768


def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts with Gemini. Vectors are L2-normalised, so a dot product is cosine similarity."""
    from google.genai import types

    out: list[list[float]] = []
    for i in range(0, len(texts), 50):  # batch to stay inside request limits
        resp = _call_embed(
            model=EMBED_MODEL,
            contents=texts[i : i + 50],
            config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=EMBED_DIM),
        )
        for e in resp.embeddings:
            v = list(e.values)
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
    return out


def _call_embed(**kw):
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        time.sleep(CALL_DELAY_S)
        try:
            return client().models.embed_content(**kw)
        except Exception as e:
            if not _is_transient(e) or attempt == RATE_LIMIT_RETRIES:
                raise
            time.sleep(15 * (attempt + 1))
