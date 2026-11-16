// Port of server/evaluator.py so assumption edits recompute in the browser,
// including on the static replay site. tests/test_parity checks both agree.
import type { Assumption, DriverTree, Evaluation, Range, Swing, TreeNode } from "./types";

type Bounds = [number, number];

function compute(nodes: Map<string, TreeNode>, values: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  const ev = (id: string): number => {
    if (id in out) return out[id];
    const n = nodes.get(id)!;
    let v: number;
    if (n.op === "input") v = values[n.assumption_id!];
    else {
      const xs = n.children.map(ev);
      if (n.op === "multiply") v = xs.reduce((a, b) => a * b, 1);
      else if (n.op === "add") v = xs.reduce((a, b) => a + b, 0);
      else if (n.op === "subtract") v = xs[0] - xs[1];
      else v = xs[1] ? xs[0] / xs[1] : 0;
    }
    out[id] = v;
    return v;
  };
  nodes.forEach((_, id) => ev(id));
  return out;
}

function intervals(nodes: Map<string, TreeNode>, assumptions: Assumption[]): Record<string, Bounds> {
  const a: Record<string, Bounds> = {};
  assumptions.forEach((x) => (a[x.id] = [x.low, x.high]));
  const out: Record<string, Bounds> = {};
  const ev = (id: string): Bounds => {
    if (id in out) return out[id];
    const n = nodes.get(id)!;
    let r: Bounds;
    if (n.op === "input") r = a[n.assumption_id!];
    else {
      const xs = n.children.map(ev);
      if (n.op === "add") r = [xs.reduce((s, x) => s + x[0], 0), xs.reduce((s, x) => s + x[1], 0)];
      else if (n.op === "subtract") r = [xs[0][0] - xs[1][1], xs[0][1] - xs[1][0]];
      else if (n.op === "multiply") {
        r = xs[0];
        for (const x of xs.slice(1)) {
          const p = [r[0] * x[0], r[0] * x[1], r[1] * x[0], r[1] * x[1]];
          r = [Math.min(...p), Math.max(...p)];
        }
      } else {
        const [lo, hi] = xs[1];
        const p = lo <= 0 && hi >= 0 ? [0, 0] : [xs[0][0] / lo, xs[0][0] / hi, xs[0][1] / lo, xs[0][1] / hi];
        r = [Math.min(...p), Math.max(...p)];
      }
    }
    out[id] = r;
    return r;
  };
  nodes.forEach((_, id) => ev(id));
  return out;
}

export function evaluate(tree: DriverTree, assumptions: Assumption[]): Evaluation {
  const nodes = new Map(tree.nodes.map((n) => [n.id, n]));
  const baseVals: Record<string, number> = {};
  assumptions.forEach((a) => (baseVals[a.id] = a.base));
  const base = compute(nodes, baseVals);
  const bounds = intervals(nodes, assumptions);
  const rng = (id: string): Range => ({
    low: bounds[id][0],
    base: base[id],
    high: bounds[id][1],
    unit: nodes.get(id)!.unit,
  });

  const swings: Swing[] = assumptions.map((a) => {
    const lo = compute(nodes, { ...baseVals, [a.id]: a.low });
    const hi = compute(nodes, { ...baseVals, [a.id]: a.high });
    return {
      assumption_id: a.id,
      value_swing: Math.abs(hi[tree.root_value_id] - lo[tree.root_value_id]),
      impact_swing: Math.abs(hi[tree.root_impact_id] - lo[tree.root_impact_id]),
      rank: 0,
    };
  });
  const vb = Math.abs(base[tree.root_value_id]) || 1;
  const ib = Math.abs(base[tree.root_impact_id]) || 1;
  swings.sort((x, y) => y.value_swing / vb + y.impact_swing / ib - (x.value_swing / vb + x.impact_swing / ib));
  swings.forEach((s, i) => (s.rank = i + 1));

  const node_values: Record<string, Range> = {};
  nodes.forEach((_, id) => (node_values[id] = rng(id)));
  return { value: rng(tree.root_value_id), impact: rng(tree.root_impact_id), node_values, sensitivity: swings };
}
