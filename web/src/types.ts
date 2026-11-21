// Mirrors server/schema.py. The UI is a pure function of the event list.

export type ClaimKind = "value" | "impact" | "traction" | "market";
export type Stance = "supports" | "contradicts" | "context";
export type Status = "supported" | "needs evidence" | "not attributable";
export type Op = "input" | "multiply" | "add" | "subtract" | "divide";

export interface Claim {
  id: string;
  text: string;
  quote: string;
  source_url: string;
  kind: ClaimKind;
  quantity?: number | null;
  unit?: string | null;
}

export interface Evidence {
  id: string;
  claim_id: string;
  stance: Stance;
  summary: string;
  url: string;
  publisher: string;
}

export interface Objection {
  id: string;
  claim_id: string;
  text: string;
  severity: number;
  what_would_resolve_it: string;
}

export interface Verdict {
  claim_id: string;
  status: Status;
  reason: string;
}

export interface Assumption {
  id: string;
  label: string;
  low: number;
  base: number;
  high: number;
  unit: string;
  source_url?: string | null;
  source_note?: string | null;
  judgement_call: boolean;
  claim_ids: string[];
}

export interface TreeNode {
  id: string;
  label: string;
  op: Op;
  children: string[];
  assumption_id?: string | null;
  unit: string;
}

export interface DriverTree {
  root_value_id: string;
  root_impact_id: string;
  nodes: TreeNode[];
}

export interface Range {
  low: number;
  base: number;
  high: number;
  unit: string;
}

export interface Swing {
  assumption_id: string;
  value_swing: number;
  impact_swing: number;
  rank: number;
}

export interface Evaluation {
  value: Range;
  impact: Range;
  node_values: Record<string, Range>;
  sensitivity: Swing[];
}

export interface Question {
  id: string;
  text: string;
  targets_assumption_id: string;
  sensitivity_rank: number;
  why_it_matters: string;
  asked_before?: boolean;
}

export interface MemoryRecord {
  id: string;
  company: string;
  run_id: string;
  run_date: string;
  source_url: string;
  kind: "claim" | "assumption" | "question";
  text: string;
  summary: string;
  data: Record<string, any>;
}

export interface MemoryItem {
  role: "history" | "comparable";
  record: MemoryRecord;
  score?: number | null;
  for_label?: string;
}

export interface Diff {
  previous_run: string;
  previous_date: string;
  claims: { claim_id?: string; text: string; change: string; before?: string; now?: string; memory_id?: string }[];
  assumptions: {
    assumption_id: string; label: string; change: string; memory_id?: string;
    before?: { low: number; base: number; high: number; unit: string };
    now?: { low: number; base: number; high: number; unit: string };
    became_sourced?: boolean;
  }[];
  questions: { text: string; memory_id: string; status: string }[];
}

export interface RunEvent {
  run_id: string;
  seq: number;
  ts: number;
  type: string;
  agent?: string | null;
  payload: Record<string, any>;
}
