"""Sceptic: claim + evidence -> objections and a verdict."""
from __future__ import annotations

from .. import llm
from ..schema import Claim, Evidence, Objection, ScepticOut, Verdict
from . import prompt


def run(company: str, claim: Claim, evidence: list[Evidence]) -> tuple[list[Objection], Verdict]:
    ev = "\n".join(f"- [{e.stance}] {e.summary} ({e.publisher})" for e in evidence) or "- none found"
    out = llm.generate_json(
        prompt("sceptic", company=company, claim=claim.text, quote=claim.quote,
               source_url=claim.source_url, evidence=ev, claim_id=claim.id),
        ScepticOut,
        model=llm.MODEL_STRONG,
    )
    for o in out.objections:
        o.claim_id = claim.id
    out.verdict.claim_id = claim.id
    return out.objections[:2], out.verdict
