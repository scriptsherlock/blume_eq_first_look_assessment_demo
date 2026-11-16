"""Extractor: page text -> claims with verbatim quotes."""
from __future__ import annotations

from .. import llm
from ..fetch import quote_in_text
from ..schema import Claim, ExtractorOut
from . import prompt

MAX_CLAIMS = 8


def run(url: str, title: str, text: str) -> tuple[str, list[Claim], list[Claim]]:
    """Returns (company, kept claims, dropped claims)."""
    out = llm.generate_json(
        prompt("extractor", url=url, title=title, text=text[:30000], max_claims=MAX_CLAIMS),
        ExtractorOut,
        model=llm.MODEL_FAST,
    )
    kept, dropped = [], []
    for c in out.claims[:MAX_CLAIMS]:
        c.source_url = url
        (kept if quote_in_text(c.quote, text) else dropped).append(c)
    return out.company, kept, dropped
