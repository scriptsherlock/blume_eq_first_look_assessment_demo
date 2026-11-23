"""Keyless web search for the Researcher agent.

Uses DuckDuckGo through the `ddgs` library, which needs no account or API key.
It is unofficial: results can be rate-limited or change without notice, so
every caller must cope with an empty list or an exception.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

from .fetch import fetch

PAGE_CHARS = 6000
PAUSE_S = 1.5  # DuckDuckGo throttles rapid queries
PAGE_TIMEOUT_S = 6
_last_query = 0.0


@dataclass
class Hit:
    url: str
    title: str
    snippet: str

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.removeprefix("www.")


def web_search(query: str, k: int = 5) -> list[Hit]:
    """Search results, or [] when there are none. Raises only when search itself fails."""
    global _last_query
    from ddgs import DDGS

    wait = PAUSE_S - (time.monotonic() - _last_query)
    if wait > 0:
        time.sleep(wait)
    try:
        rows = DDGS().text(query, max_results=k)
    except Exception as e:
        if "no results" in str(e).lower():
            return []  # nothing found is an answer, not a failure
        raise
    finally:
        _last_query = time.monotonic()
    return [Hit(url=r.get("href", ""), title=r.get("title", ""), snippet=r.get("body", ""))
            for r in rows or [] if r.get("href")]


def read_page(url: str) -> str | None:
    """Plain text of a page, or None if it can't be fetched. Code reads the page, not the model."""
    try:
        _, text = fetch(url, timeout=PAGE_TIMEOUT_S)
    except Exception:
        return None
    return text[:PAGE_CHARS] if len(text) > 300 else None
