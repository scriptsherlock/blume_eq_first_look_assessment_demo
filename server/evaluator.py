"""Deterministic maths for the driver tree.

The Modeller agent designs the tree; this file only computes it. It checks
structure, evaluates both roots at low/base/high, and ranks assumptions by
one-at-a-time swing.
"""
from __future__ import annotations

from .schema import Assumption, DriverTree, Evaluation, Node, Range, Swing


class TreeError(ValueError):
    pass


def validate(tree: DriverTree, assumptions: list[Assumption]) -> None:
    nodes = {n.id: n for n in tree.nodes}
    a_ids = {a.id for a in assumptions}
    if len(nodes) != len(tree.nodes):
        raise TreeError("duplicate node ids")
    for root in (tree.root_value_id, tree.root_impact_id):
        if root not in nodes:
            raise TreeError(f"root {root!r} is not a node")
    for n in tree.nodes:
        if n.op == "input":
            if n.children:
                raise TreeError(f"input node {n.id!r} has children")
            if n.assumption_id not in a_ids:
                raise TreeError(f"input node {n.id!r} references unknown assumption {n.assumption_id!r}")
        else:
            if not n.children:
                raise TreeError(f"node {n.id!r} ({n.op}) has no children")
            if n.op in ("subtract", "divide") and len(n.children) != 2:
                raise TreeError(f"node {n.id!r} ({n.op}) needs exactly 2 children")
            for c in n.children:
                if c not in nodes:
                    raise TreeError(f"node {n.id!r} references missing child {c!r}")
    # cycle check
    state: dict[str, int] = {}

    def visit(nid: str) -> None:
        if state.get(nid) == 1:
            raise TreeError(f"cycle through {nid!r}")
        if state.get(nid) == 2:
            return
        state[nid] = 1
        for c in nodes[nid].children:
            visit(c)
        state[nid] = 2

    for n in tree.nodes:
        visit(n.id)
    for a in assumptions:
        if not (a.low <= a.base <= a.high):
            raise TreeError(f"assumption {a.id!r} violates low <= base <= high")
        if not a.source_url and not a.judgement_call:
            raise TreeError(f"assumption {a.id!r} has no source and is not flagged as a judgement call")


def _compute(nodes: dict[str, Node], values: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}

    def ev(nid: str) -> float:
        if nid in out:
            return out[nid]
        n = nodes[nid]
        if n.op == "input":
            v = values[n.assumption_id]  # type: ignore[index]
        else:
            xs = [ev(c) for c in n.children]
            if n.op == "multiply":
                v = 1.0
                for x in xs:
                    v *= x
            elif n.op == "add":
                v = sum(xs)
            elif n.op == "subtract":
                v = xs[0] - xs[1]
            elif n.op == "divide":
                v = xs[0] / xs[1] if xs[1] else 0.0
            else:  # pragma: no cover - guarded by schema
                raise TreeError(f"unknown op {n.op}")
        out[nid] = v
        return v

    for nid in nodes:
        ev(nid)
    return out


def _intervals(nodes: dict[str, Node], assumptions: list[Assumption]) -> dict[str, tuple[float, float]]:
    """Interval arithmetic: the true low/high envelope of each node.

    Plugging every assumption's low into the tree does not give the low result
    when a divide or subtract flips direction, so bounds are propagated instead.
    """
    a = {x.id: (x.low, x.high) for x in assumptions}
    out: dict[str, tuple[float, float]] = {}

    def ev(nid: str) -> tuple[float, float]:
        if nid in out:
            return out[nid]
        n = nodes[nid]
        if n.op == "input":
            r = a[n.assumption_id]  # type: ignore[index]
        else:
            xs = [ev(c) for c in n.children]
            if n.op == "add":
                r = (sum(x[0] for x in xs), sum(x[1] for x in xs))
            elif n.op == "subtract":
                r = (xs[0][0] - xs[1][1], xs[0][1] - xs[1][0])
            elif n.op == "multiply":
                r = xs[0]
                for x in xs[1:]:
                    p = [r[0] * x[0], r[0] * x[1], r[1] * x[0], r[1] * x[1]]
                    r = (min(p), max(p))
            else:  # divide
                lo, hi = xs[1]
                if lo <= 0 <= hi:
                    raise TreeError(f"node {nid!r} divides by a range that includes zero")
                p = [xs[0][0] / lo, xs[0][0] / hi, xs[0][1] / lo, xs[0][1] / hi]
                r = (min(p), max(p))
        out[nid] = r
        return r

    for nid in nodes:
        ev(nid)
    return out


def evaluate(tree: DriverTree, assumptions: list[Assumption]) -> Evaluation:
    validate(tree, assumptions)
    nodes = {n.id: n for n in tree.nodes}
    base = _compute(nodes, {a.id: a.base for a in assumptions})
    bounds = _intervals(nodes, assumptions)

    def rng(nid: str) -> Range:
        lo, hi = bounds[nid]
        return Range(low=lo, base=base[nid], high=hi, unit=nodes[nid].unit)

    base_vals = {a.id: a.base for a in assumptions}
    swings: list[Swing] = []
    for a in assumptions:
        lo = _compute(nodes, {**base_vals, a.id: a.low})
        hi = _compute(nodes, {**base_vals, a.id: a.high})
        swings.append(
            Swing(
                assumption_id=a.id,
                value_swing=abs(hi[tree.root_value_id] - lo[tree.root_value_id]),
                impact_swing=abs(hi[tree.root_impact_id] - lo[tree.root_impact_id]),
                rank=0,
            )
        )

    # Rank by swing relative to each root's base so £ and tCO2e are comparable.
    vb = abs(base[tree.root_value_id]) or 1.0
    ib = abs(base[tree.root_impact_id]) or 1.0
    swings.sort(key=lambda s: -(s.value_swing / vb + s.impact_swing / ib))
    for i, s in enumerate(swings, 1):
        s.rank = i

    return Evaluation(
        value=rng(tree.root_value_id),
        impact=rng(tree.root_impact_id),
        node_values={nid: rng(nid) for nid in nodes},
        sensitivity=swings,
    )
