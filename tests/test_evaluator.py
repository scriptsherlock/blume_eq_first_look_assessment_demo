import pytest

from server.evaluator import TreeError, evaluate, validate
from server.schema import Assumption, DriverTree, Node


def A(id, low, base, high, unit="x", judgement=True):
    return Assumption(id=id, label=id, low=low, base=base, high=high, unit=unit, judgement_call=judgement)


def small_tree():
    # value = miles * share / miles_per_visit * cost ; impact = miles * share * factor
    assumptions = [
        A("miles", 100, 200, 300),
        A("share", 0.5, 0.5, 0.5),
        A("mpv", 10, 20, 40),
        A("cost", 100, 100, 100),
        A("factor", 2, 2, 2),
    ]
    nodes = [
        Node(id="i_m", label="", op="input", assumption_id="miles"),
        Node(id="i_s", label="", op="input", assumption_id="share"),
        Node(id="i_v", label="", op="input", assumption_id="mpv"),
        Node(id="i_c", label="", op="input", assumption_id="cost"),
        Node(id="i_f", label="", op="input", assumption_id="factor"),
        Node(id="attr", label="", op="multiply", children=["i_m", "i_s"]),
        Node(id="visits", label="", op="divide", children=["attr", "i_v"]),
        Node(id="value", label="", op="multiply", children=["visits", "i_c"]),
        Node(id="impact", label="", op="multiply", children=["attr", "i_f"]),
    ]
    return DriverTree(root_value_id="value", root_impact_id="impact", nodes=nodes), assumptions


def test_base_values_match_hand_calculation():
    tree, a = small_tree()
    ev = evaluate(tree, a)
    assert ev.value.base == pytest.approx(200 * 0.5 / 20 * 100)  # 500
    assert ev.impact.base == pytest.approx(200 * 0.5 * 2)  # 200


def test_interval_bounds_handle_divide_direction():
    tree, a = small_tree()
    ev = evaluate(tree, a)
    # lowest value: fewest miles and the most miles per visit
    assert ev.value.low == pytest.approx(100 * 0.5 / 40 * 100)  # 125
    assert ev.value.high == pytest.approx(300 * 0.5 / 10 * 100)  # 1500
    assert ev.impact.low == pytest.approx(100)
    assert ev.impact.high == pytest.approx(300)
    for r in (ev.value, ev.impact):
        assert r.low <= r.base <= r.high


def test_sensitivity_ranks_varying_assumptions_first():
    tree, a = small_tree()
    ev = evaluate(tree, a)
    ranked = [s.assumption_id for s in ev.sensitivity]
    assert set(ranked[:2]) == {"miles", "mpv"}
    assert [s.rank for s in ev.sensitivity] == list(range(1, len(a) + 1))


def test_rejects_cycle():
    tree, a = small_tree()
    tree.nodes[5].children = ["i_m", "impact"]  # attr -> impact -> attr
    with pytest.raises(TreeError, match="cycle"):
        validate(tree, a)


def test_rejects_missing_child_and_unknown_assumption():
    tree, a = small_tree()
    tree.nodes[6].children = ["attr", "nope"]
    with pytest.raises(TreeError, match="missing child"):
        validate(tree, a)
    tree, a = small_tree()
    tree.nodes[0].assumption_id = "ghost"
    with pytest.raises(TreeError, match="unknown assumption"):
        validate(tree, a)


def test_rejects_unsourced_assumption():
    tree, a = small_tree()
    a[0] = A("miles", 100, 200, 300, judgement=False)
    with pytest.raises(TreeError, match="no source"):
        validate(tree, a)


def test_rejects_bad_ordering():
    tree, a = small_tree()
    a[0] = A("miles", 300, 200, 100)
    with pytest.raises(TreeError, match="low <= base <= high"):
        validate(tree, a)


def test_rejects_divide_by_range_including_zero():
    tree, a = small_tree()
    a[2] = A("mpv", 0, 20, 40)
    with pytest.raises(TreeError, match="zero"):
        evaluate(tree, a)
