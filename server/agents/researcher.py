"""Researcher: one claim -> independent evidence via Google Search grounding.

Two calls: a grounded call (prose + sources from grounding metadata), then a
structuring call that may only cite those sources by index.
"""
from __future__ import annotations

from urllib.parse import urlparse

from .. import llm
from ..schema import Claim, Evidence, ResearcherOut
from . import prompt


def run(company: str, claim: Claim) -> list[Evidence]:
    domain = urlparse(claim.source_url).netloc
    report, sources = llm.generate_grounded(
        prompt("researcher", company=company, claim=claim.text, quote=claim.quote,
               source_url=claim.source_url, source_domain=domain),
        model=llm.MODEL_FAST,
    )
    if not sources:
        return []
    numbered = "\n".join(f"[{i}] {s.title} {s.url}" for i, s in enumerate(sources))
    out = llm.generate_json(
        prompt("researcher_structure", claim=claim.text, report=report, sources=numbered),
        ResearcherOut,
        model=llm.MODEL_FAST,
    )
    evidence = []
    for i, item in enumerate(out.items[:3], 1):
        if not 0 <= item.source_index < len(sources):
            continue  # model cited a source that grounding did not return
        src = sources[item.source_index]
        if domain and domain in src.title:
            continue  # not independent
        evidence.append(Evidence(id=f"e_{claim.id}_{i}", claim_id=claim.id, stance=item.stance,
                                 summary=item.summary, url=src.url, publisher=src.title))
    return evidence
