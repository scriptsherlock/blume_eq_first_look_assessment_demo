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

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class PageUnreadable(RuntimeError):
    """The page could not be read; the message says what to try instead."""


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
    try:
        r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=timeout)
    except httpx.HTTPError as e:
        raise PageUnreadable(
            "Could not read the page: the site closed the connection or did not answer. Many large sites block "
            "automated readers. Try a press release, case study or news article about the company instead."
        ) from e
    if r.status_code in (401, 403, 429):
        raise PageUnreadable(
            f"This site refuses automated readers (error {r.status_code}). "
            "Try a press release, case study or news article about the company instead."
        )
    if r.status_code >= 400:
        raise PageUnreadable(f"The page returned error {r.status_code}. Check the address and try again.")
    return html_to_text(r.text)


def quote_in_text(quote: str, text: str) -> bool:
    q = normalise(quote).lower()
    return len(q) >= 12 and q in normalise(text).lower()
