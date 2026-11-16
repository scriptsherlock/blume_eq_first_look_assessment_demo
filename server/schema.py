"""Data model shared by agents, evaluator, store and the front end."""
from __future__ import annotations

import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ClaimKind = Literal["value", "impact", "traction", "market"]
Stance = Literal["supports", "contradicts", "context"]
Status = Literal["supported", "needs evidence", "not attributable"]
Op = Literal["input", "multiply", "add", "subtract", "divide"]


class Claim(BaseModel):
    id: str
    text: str = Field(description="The claim restated in plain words")
    quote: str = Field(description="Exact sentence or phrase from the page, copied verbatim")
    source_url: str = ""
    kind: ClaimKind
    quantity: Optional[float] = None
    unit: Optional[str] = None


class Evidence(BaseModel):
    id: str
    claim_id: str
    stance: Stance
    summary: str
    url: str
    publisher: str = ""


class Objection(BaseModel):
    id: str
    claim_id: str
    text: str
    severity: int = Field(ge=1, le=3)
    what_would_resolve_it: str


class Verdict(BaseModel):
    claim_id: str
    status: Status
    reason: str


class Assumption(BaseModel):
    id: str
    label: str
    low: float
    base: float
    high: float
    unit: str
    source_url: Optional[str] = None
    source_note: Optional[str] = None
    judgement_call: bool = False
    claim_ids: list[str] = Field(default_factory=list)


class Node(BaseModel):
    id: str
    label: str
    op: Op
    children: list[str] = Field(default_factory=list)
    assumption_id: Optional[str] = None
    unit: str = ""


class DriverTree(BaseModel):
    root_value_id: str
    root_impact_id: str
    nodes: list[Node]


class Question(BaseModel):
    id: str
    text: str
    targets_assumption_id: str
    sensitivity_rank: int
    why_it_matters: str


# ---- agent output envelopes (what the LLM is asked to return) ----

class ExtractorOut(BaseModel):
    company: str
    claims: list[Claim]


class EvidenceItem(BaseModel):
    stance: Stance
    summary: str
    source_index: int = Field(description="Index into the numbered source list provided")


class ResearcherOut(BaseModel):
    items: list[EvidenceItem]


class ScepticOut(BaseModel):
    objections: list[Objection]
    verdict: Verdict


class ModellerOut(BaseModel):
    assumptions: list[Assumption]
    tree: DriverTree
    rationale: str


class QuestionerOut(BaseModel):
    questions: list[Question]


# ---- evaluator output ----

class Range(BaseModel):
    low: float
    base: float
    high: float
    unit: str = ""


class Swing(BaseModel):
    assumption_id: str
    value_swing: float
    impact_swing: float
    rank: int


class Evaluation(BaseModel):
    value: Range
    impact: Range
    node_values: dict[str, Range]
    sensitivity: list[Swing]


# ---- events ----

EventType = Literal[
    "run_started",
    "agent_started",
    "claim_added",
    "evidence_added",
    "objection_added",
    "verdict_set",
    "assumption_added",
    "tree_node_added",
    "tree_evaluated",
    "question_added",
    "agent_finished",
    "run_finished",
    "error",
]


class Event(BaseModel):
    run_id: str
    seq: int
    ts: float = Field(default_factory=time.time)
    type: EventType
    agent: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
