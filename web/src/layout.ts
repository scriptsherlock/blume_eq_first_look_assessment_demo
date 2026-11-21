// Turns view state into React Flow nodes and edges, in fixed columns:
// source -> claims -> evidence & objections -> assumptions -> driver tree -> outputs.
import type { Edge, Node } from "@xyflow/react";
import type { Assumption, Evaluation, TreeNode } from "./types";
import type { State } from "./reducer";

export const COL_W = 330;
const GAP = 24;

export type CardKind = "source" | "claim" | "evidence" | "objection" | "memory" | "assumption" | "op" | "output";
export interface CardData extends Record<string, unknown> {
  kind: CardKind;
  refId: string;
}

function h(kind: CardKind): number {
  return { source: 120, claim: 128, evidence: 100, objection: 100, memory: 96, assumption: 104, op: 70, output: 120 }[kind];
}

export function buildGraph(s: State, assumptions: Assumption[], ev: Evaluation | undefined, selected: string | null) {
  const nodes: Node<CardData>[] = [];
  const edges: Edge[] = [];
  const add = (id: string, kind: CardKind, refId: string, x: number, y: number) =>
    nodes.push({ id, type: "card", position: { x, y }, data: { kind, refId }, selected: id === selected });

  if (!s.url) return { nodes, edges };
  add("source", "source", "source", 0, 0);

  // claims
  let y = 0;
  const claimY: Record<string, number> = {};
  s.claims.forEach((c) => {
    claimY[c.id] = y;
    add(`claim:${c.id}`, "claim", c.id, COL_W, y);
    edges.push({ id: `e-src-${c.id}`, source: "source", target: `claim:${c.id}`, className: "edge-soft" });
    y += h("claim") + GAP;
  });

  // evidence and objections, kept level with their claim where possible
  y = 0;
  s.claims.forEach((c) => {
    y = Math.max(y, claimY[c.id]);
    const items = [
      ...s.evidence.filter((e) => e.claim_id === c.id).map((e) => ({ kind: "evidence" as const, id: e.id, tone: e.stance })),
      ...s.objections.filter((o) => o.claim_id === c.id).map((o) => ({ kind: "objection" as const, id: o.id, tone: "objection" })),
    ];
    items.forEach((it) => {
      add(`${it.kind}:${it.id}`, it.kind, it.id, COL_W * 2, y);
      edges.push({
        id: `e-${it.id}`, source: `${it.kind}:${it.id}`, target: `claim:${c.id}`,
        className: `edge-${it.tone}`, sourceHandle: "l", targetHandle: "r2",
      });
      y += h(it.kind) + GAP;
    });
  });

  // memory: earlier looks at this company, then comparables from other companies
  const memCol = s.memory.length > 0 ? 1 : 0;
  y = 0;
  const memIds = new Set<string>();
  const linkedClaims = new Set((s.diff?.claims ?? []).filter((c) => c.claim_id && c.memory_id).map((c) => c.memory_id));
  [...s.memory.filter((m) => m.role === "history" && (m.record.kind === "assumption" || linkedClaims.has(m.record.id))),
   ...s.memory.filter((m) => m.role === "comparable")].forEach((m) => {
    memIds.add(m.record.id);
    add(`memory:${m.record.id}`, "memory", m.record.id, COL_W * 3, y);
    y += h("memory") + GAP;
  });
  // a repeated claim links back to how it was judged last time
  s.diff?.claims.forEach((c) => {
    if (c.claim_id && c.memory_id && memIds.has(c.memory_id))
      edges.push({ id: `e-mem-${c.memory_id}-${c.claim_id}`, source: `claim:${c.claim_id}`, target: `memory:${c.memory_id}`,
                   className: "edge-memory" });
  });
  const AX = COL_W * (3 + memCol);

  // assumptions
  const rank: Record<string, number> = {};
  ev?.sensitivity.forEach((sw) => (rank[sw.assumption_id] = sw.rank));
  const nA = Math.max(assumptions.length, 1);
  y = 0;
  assumptions.forEach((a) => {
    add(`assumption:${a.id}`, "assumption", a.id, AX, y);
    (a.source_note?.match(/mem-[0-9a-f]{8}/g) ?? []).forEach((mid) => {
      if (memIds.has(mid))
        edges.push({ id: `e-${mid}-${a.id}`, source: `memory:${mid}`, target: `assumption:${a.id}`, className: "edge-memory" });
    });
    a.claim_ids.forEach((cid) => {
      if (claimY[cid] !== undefined)
        edges.push({ id: `e-${cid}-${a.id}`, source: `claim:${cid}`, target: `assumption:${a.id}`, className: "edge-claim" });
    });
    y += h("assumption") + GAP;
  });

  // tree: input nodes are drawn as their assumption card; ops are laid out by depth
  const byId = new Map<string, TreeNode>(s.treeNodes.map((n) => [n.id, n]));
  const depth: Record<string, number> = {};
  const d = (id: string): number => {
    if (id in depth) return depth[id];
    const n = byId.get(id);
    if (!n || n.op === "input") return (depth[id] = 0);
    return (depth[id] = 1 + Math.max(0, ...n.children.filter((c) => byId.has(c)).map(d)));
  };
  const ops = s.treeNodes.filter((n) => n.op !== "input");
  ops.forEach((n) => d(n.id));
  const maxD = Math.max(1, ...ops.map((n) => depth[n.id]));
  const isRoot = (id: string) => id === s.roots.value || id === s.roots.impact;
  const cols: Record<number, TreeNode[]> = {};
  ops.forEach((n) => {
    const col = isRoot(n.id) ? maxD + 1 : depth[n.id];
    (cols[col] ||= []).push(n);
  });
  Object.entries(cols).forEach(([col, list]) => {
    const c = Number(col);
    const total = list.reduce((t, n) => t + h(isRoot(n.id) ? "output" : "op") + GAP * 3, 0);
    let yy = Math.max(0, (assumptions.length * (h("assumption") + GAP)) / 2 - total / 2);
    list.forEach((n) => {
      const kind = isRoot(n.id) ? "output" : "op";
      add(`tree:${n.id}`, kind, n.id, AX + COL_W + (c - 1) * (COL_W * 0.78), yy);
      yy += h(kind) + GAP * 3;
    });
  });
  ops.forEach((n) => {
    n.children.forEach((cid) => {
      const child = byId.get(cid);
      if (!child) return;
      if (child.op === "input" && child.assumption_id) {
        const r = rank[child.assumption_id];
        const w = r ? 1.5 + 5 * (1 - (r - 1) / nA) : 1.5;
        edges.push({
          id: `e-${child.assumption_id}-${n.id}`, source: `assumption:${child.assumption_id}`, target: `tree:${n.id}`,
          className: "edge-tree", style: { strokeWidth: w },
        });
      } else {
        edges.push({ id: `e-${cid}-${n.id}`, source: `tree:${cid}`, target: `tree:${n.id}`, className: "edge-tree", style: { strokeWidth: 2.5 } });
      }
    });
  });

  return { nodes, edges };
}
