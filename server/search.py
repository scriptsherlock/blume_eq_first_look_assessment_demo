"""Keyless web search for the Researcher agent.

Uses the `ddgs` library (Bing, Google, Yahoo, DuckDuckGo), which needs no account
or API key. It is unofficial: results can be rate-limited or change without notice,
so every caller must cope with an empty list or an exception.
Set SEARCH_BACKENDS in .env to change the order, e.g. "google,bing".
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from .fetch import fetch

PAGE_CHARS = 6000
PAUSE_S = 1.5  # DuckDuckGo throttles rapid queries
PAGE_TIMEOUT_S = 6
DEFAULT_BACKENDS = "bing,google,yahoo,duckduckgo"
AD_PATTERNS = ("bing.com/aclick", "duckduckgo.com/y.js", "googleadservices.com", "/aclk?")
_last_query = 0.0


@dataclass
class Hit:
    url: str
    title: str
    snippet: str

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.removeprefix("www.")


def _backends() -> list[str]:
    return [b.strip() for b in os.getenv("SEARCH_BACKENDS", DEFAULT_BACKENDS).split(",") if b.strip()]


def _is_ad(url: str) -> bool:
    return any(p in url for p in AD_PATTERNS)


def web_search(query: str, k: int = 5) -> list[Hit]:
    """Search results, or [] when there are none. Raises only when every backend errors.

    Free search engines answer automated queries only some of the time, and often say
    "No results found" when they are really throttling. So each query tries the
    backends in turn and returns the first non-empty answer.
    """
    global _last_query
    from ddgs import DDGS

    errors: list[Exception] = []
    for backend in _backends():
        wait = PAUSE_S - (time.monotonic() - _last_query)
        if wait > 0:
            time.sleep(wait)
        try:
            rows = DDGS().text(query, max_results=k, backend=backend)
        except Exception as e:
            if "no results" not in str(e).lower():
                errors.append(e)
            continue
        finally:
            _last_query = time.monotonic()
        hits = [Hit(url=r.get("href", ""), title=r.get("title", ""), snippet=r.get("body", ""))
                for r in rows or [] if r.get("href") and not _is_ad(r["href"])]
        if hits:
            return hits
    if errors and len(errors) == len(_backends()):
        raise errors[-1]
    return []  # nothing found is an answer, not a failure


def read_page(url: str) -> str | None:
    """Plain text of a page, or None if it can't be fetched. Code reads the page, not the model."""
    try:
        _, text = fetch(url, timeout=PAGE_TIMEOUT_S)
    except Exception:
        return None
    return text[:PAGE_CHARS] if len(text) > 300 else None
