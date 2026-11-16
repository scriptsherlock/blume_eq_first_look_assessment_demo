"""Fetch a web page and reduce it to readable paragraphs.

Some sites (Framer, which Blume uses) ship article text inside an embedded
JSON blob as well as in the HTML. We take visible text from the HTML and fall
back to the JSON rich-text strings if the HTML yields too little.
"""
from __future__ import annotations

import json
import re
import unicodedata

import httpx
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; evidence-map-demo/0.1)"


def normalise(text: str) -> str:
    """Normalise whitespace and typographic quotes so verbatim checks are fair."""
    text = unicodedata.normalize("NFKC", text)
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
    )
    return re.sub(r"\s+", " ", text).strip()


def _framer_richtext(html: str) -> list[str]:
    """Pull paragraph strings out of Framer's serialised rich text."""
    paras: list[str] = []
    for m in re.finditer(r'\[5,\\"((?:[^"\\]|\\\\.|\\[^"])*?)\\"\]', html):
        raw = m.group(1)
        try:
            s = json.loads('"' + raw.replace('\\\\', '\\') + '"')
        except json.JSONDecodeError:
            s = raw
        if len(s) > 60:
            paras.append(s)
    return paras


def html_to_text(html: str) -> tuple[str, str]:
    """Return (title, text)."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()
    # h1 is skipped: Framer splits it into per-letter spans, and the title is known anyway.
    blocks = [p.get_text(" ", strip=True) for p in soup.find_all(["p", "h2", "h3", "li"])]
    blocks = [b for b in blocks if len(b) > 40]
    text = "\n\n".join(dict.fromkeys(blocks))
    if len(text) < 800:
        framer = _framer_richtext(html)
        if framer:
            text = "\n\n".join(dict.fromkeys(framer))
    return title, text


def fetch(url: str, timeout: float = 20.0) -> tuple[str, str]:
    r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    return html_to_text(r.text)


def quote_in_text(quote: str, text: str) -> bool:
    q = normalise(quote).lower()
    return len(q) >= 12 and q in normalise(text).lower()
