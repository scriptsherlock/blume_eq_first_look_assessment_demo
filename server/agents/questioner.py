"""Questioner: ranked assumptions + objections -> five founder questions."""
from __future__ import annotations

from .. import llm
from ..schema import Assumption, Evaluation, Objection, Question, QuestionerOut
from . import prompt


def run(company: str, assumptions: list[Assumption], evaluation: Evaluation, objections: list[Objection]) -> list[Question]:
    by_id = {a.id: a for a in assumptions}
    ranked = "\n".join(
        f"{s.rank}. {s.assumption_id} {by_id[s.assumption_id].label} "
        f"(base {by_id[s.assumption_id].base} {by_id[s.assumption_id].unit}, "
        f"{'judgement call' if by_id[s.assumption_id].judgement_call else 'sourced'})"
        for s in evaluation.sensitivity
    )
    obj = "\n".join(f"- (severity {o.severity}) {o.text}" for o in objections) or "- none"
    ranks = {s.assumption_id: s.rank for s in evaluation.sensitivity}
    out = llm.generate_json(prompt("questioner", company=company, ranked=ranked, objections=obj),
                            QuestionerOut, model=llm.MODEL_FAST)
    qs, seen = [], set()
    for q in out.questions:
        if q.targets_assumption_id in by_id and q.targets_assumption_id not in seen:
            seen.add(q.targets_assumption_id)
            qs.append(q)
    qs = sorted(qs, key=lambda q: ranks[q.targets_assumption_id])[:5]
    for q in qs:
        q.sensitivity_rank = ranks[q.targets_assumption_id]
    return qs
