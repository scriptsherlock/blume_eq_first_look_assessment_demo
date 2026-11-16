// Folds the event log into view state. Replay and live mode share this.
import type {
  Assumption, Claim, DriverTree, Evaluation, Evidence, Objection, Question, RunEvent, TreeNode, Verdict,
} from "./types";

export interface AgentStep {
  agent: string;
  detail?: string;
  seq: number;
  done: boolean;
}

export interface State {
  runId: string;
  url: string;
  mode: string; // "live" | "sample" | "replay"
  label: string;
  note: string;
  company: string;
  claims: Claim[];
  dropped: { text: string; quote: string }[];
  evidence: Evidence[];
  objections: Objection[];
  verdicts: Record<string, Verdict>;
  revision: number;
  assumptions: Assumption[];
  treeNodes: TreeNode[];
  roots: { value?: string; impact?: string };
  tree?: DriverTree;
  evaluation?: Evaluation;
  rationale: string;
  questions: Question[];
  steps: AgentStep[];
  activeAgent: string | null;
  finished: boolean;
  error: string | null;
  notes: string[];
}

export const empty: State = {
  runId: "", url: "", mode: "", label: "", note: "", company: "",
  claims: [], dropped: [], evidence: [], objections: [], verdicts: {},
  revision: 0, assumptions: [], treeNodes: [], roots: {}, rationale: "", questions: [],
  steps: [], activeAgent: null, finished: false, error: null, notes: [],
};

function resetModelIfNewRevision(s: State, rev: number | undefined): State {
  if (rev === undefined || rev <= s.revision) return s;
  return { ...s, revision: rev, assumptions: [], treeNodes: [], roots: {}, tree: undefined,
           evaluation: undefined, questions: [], rationale: "" };
}

export function reduce(s: State, e: RunEvent): State {
  const p = e.payload || {};
  switch (e.type) {
    case "run_started":
      return { ...s, runId: e.run_id, url: p.url, mode: p.mode, label: p.label, note: p.note || "",
               finished: false, error: null };
    case "agent_started": {
      const steps = s.steps.map((x) => ({ ...x, done: true }));
      const claim = p.claim_id ? s.claims.find((c) => c.id === p.claim_id) : undefined;
      const detail = claim ? claim.text : p.instruction;
      return { ...s, activeAgent: e.agent!, finished: false,
               steps: [...steps, { agent: e.agent!, detail, seq: e.seq, done: false }] };
    }
    case "agent_finished":
      return { ...s, company: p.company ?? s.company, dropped: p.dropped ?? s.dropped,
               notes: p.note ? [...s.notes, p.note] : s.notes,
               steps: s.steps.map((x) => (x.agent === e.agent ? { ...x, done: true } : x)) };
    case "claim_added":
      return { ...s, claims: [...s.claims, p.claim] };
    case "evidence_added":
      return { ...s, evidence: [...s.evidence, p.evidence] };
    case "objection_added":
      return { ...s, objections: [...s.objections, p.objection] };
    case "verdict_set":
      return { ...s, verdicts: { ...s.verdicts, [p.verdict.claim_id]: p.verdict } };
    case "assumption_added": {
      const t = resetModelIfNewRevision(s, p.revision);
      return { ...t, assumptions: [...t.assumptions, p.assumption] };
    }
    case "tree_node_added": {
      const t = resetModelIfNewRevision(s, p.revision);
      const roots = { ...t.roots };
      if (p.is_value_root) roots.value = p.node.id;
      if (p.is_impact_root) roots.impact = p.node.id;
      return { ...t, treeNodes: [...t.treeNodes, p.node], roots };
    }
    case "tree_evaluated":
      return { ...s, tree: p.tree, evaluation: p.evaluation, rationale: p.rationale };
    case "question_added": {
      const t = resetModelIfNewRevision(s, p.revision);
      return { ...t, questions: [...t.questions, p.question] };
    }
    case "run_finished":
      return { ...s, finished: true, activeAgent: null, steps: s.steps.map((x) => ({ ...x, done: true })) };
    case "error":
      return { ...s, error: p.message, activeAgent: null, finished: true };
    default:
      return s;
  }
}

export function fold(events: RunEvent[]): State {
  return events.reduce(reduce, empty);
}
