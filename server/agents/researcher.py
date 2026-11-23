"""Researcher: one claim -> independent evidence.

Two ways to search, chosen with SEARCH_PROVIDER in .env:

- "web" (default): a small agent that needs no extra key. Gemini plans the
  queries, code searches DuckDuckGo and reads the pages itself, Gemini judges
  each page and must quote an exact sentence from it, and code checks that the
  sentence is really on the page. Links come from the search, never from the
  model.
- "gemini": Google Search grounding inside Gemini. Needs a key with search
  quota (a paid Gemini project).

SEARCH=off turns research off entirely.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from .. import llm, search
from ..fetch import quote_in_text
from ..memory import company_key
from ..schema import Claim, Evidence, ResearcherOut, SearchPlan
from . import prompt

MAX_PAGES = 4
MAX_EVIDENCE = 3
PAGE_EXCERPT = 3500


def provider() -> str:
    return os.getenv("SEARCH_PROVIDER", "web").lower()


def run(company: str, claim: Claim) -> list[Evidence]:
    if not llm.SEARCH_ENABLED:
        raise llm.SearchUnavailable("search is turned off (SEARCH=off)")
    if provider() == "gemini":
        return _run_grounded(company, claim)
    return _run_web(company, claim)


# ---------------------------------------------------------------- keyless web agent

def _excluded(claim: Claim, company: str):
    """Pages that are not independent: the page the claim came from, and the company's own site."""
    source_domain = urlparse(claim.source_url).netloc.removeprefix("www.")
    key = company_key(company)

    def bad(domain: str) -> bool:
        d = domain.lower()
        return d == source_domain or (len(key) >= 4 and key in d.replace("-", "").replace(".", ""))

    return bad


def _run_web(company: str, claim: Claim) -> list[Evidence]:
    plan = llm.generate_json(prompt("researcher_plan", company=company, claim=claim.text, quote=claim.quote),
                             SearchPlan, model=llm.MODEL_FAST)
    queries = [q for q in plan.queries if q.strip()][:2] or [f"{company} {claim.text}"]

    bad = _excluded(claim, company)
    hits, failures = [], []
    for q in queries:
        try:
            hits += search.web_search(q, k=5)
        except Exception as e:  # rate limit, network, library change
            failures.append(f"{type(e).__name__}: {e}")
    if failures and not hits:
        raise llm.SearchUnavailable("web search failed (" + "; ".join(failures)[:200] + ")")

    seen, picked = set(), []
    for h in hits:
        if h.url in seen or bad(h.domain):
            continue
        seen.add(h.url)
        picked.append(h)

    pages = []
    for h in picked:
        if len(pages) >= MAX_PAGES:
            break
        text = search.read_page(h.url)
        if text:
            pages.append((h, text))
    if not pages:
        return []

    block = "\n\n".join(f"[{i}] {h.title} ({h.domain})\n{text[:PAGE_EXCERPT]}" for i, (h, text) in enumerate(pages))
    out = llm.generate_json(prompt("researcher_judge", company=company, claim=claim.text, pages=block),
                            ResearcherOut, model=llm.MODEL_FAST)

    evidence: list[Evidence] = []
    for item in out.items:
        if len(evidence) >= MAX_EVIDENCE:
            break
        if not 0 <= item.source_index < len(pages):
            continue  # cited a page it was not given
        hit, text = pages[item.source_index]
        if not quote_in_text(item.quote, text[:PAGE_EXCERPT]):
            continue  # the proof sentence is not on the page
        evidence.append(Evidence(id=f"e_{claim.id}_{len(evidence) + 1}", claim_id=claim.id, stance=item.stance,
                                 summary=item.summary, url=hit.url, publisher=hit.domain, quote=item.quote))
    return evidence


# ---------------------------------------------------------------- Gemini grounding (needs search quota)

def _run_grounded(company: str, claim: Claim) -> list[Evidence]:
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
    for i, item in enumerate(out.items[:MAX_EVIDENCE], 1):
        if not 0 <= item.source_index < len(sources):
            continue  # model cited a source that grounding did not return
        src = sources[item.source_index]
        if domain and domain in src.title:
            continue  # not independent
        evidence.append(Evidence(id=f"e_{claim.id}_{i}", claim_id=claim.id, stance=item.stance,
                                 summary=item.summary, url=src.url, publisher=src.title))
    return evidence
