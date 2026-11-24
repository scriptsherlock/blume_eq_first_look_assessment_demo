"""Currency, emission-factor and exchange-rate guardrails on the Modeller's output."""
import pytest

from server import references
from server.agents import modeller
from server.guardrails import GuardrailError, check_currency, check_factors, currencies_in, unit_currency
from server.schema import Assumption, Claim, DriverTree, ModellerOut, Node

REFS = references.load(live_fx=False)  # saved ECB snapshot, so tests do not need the network
USD_GBP = REFS.get("FX-USD-GBP").value
SIC28 = REFS.get("SIC-28").value
URL = "https://example.com/sparetech"

CLAIMS = [
    Claim(id="c6", kind="market", text="Average spare parts inventory is $169M per company",
          quote="average spare parts inventory value of $169 million per company", quantity=169e6, unit="USD"),
]


def A(id, low, base, high, unit, **kw):
    kw.setdefault("judgement_call", not (kw.get("source_url") or kw.get("claim_ids")))
    return Assumption(id=id, label=id, low=low, base=base, high=high, unit=unit, **kw)


def I(id, a):
    return Node(id=id, label=id, op="input", assumption_id=a)


def M(id, *children, unit=""):
    return Node(id=id, label=id, op="multiply", children=list(children), unit=unit)


def good_model():
    """SPARETECH done right: USD inventory -> GBP via ECB -> spend multiplier."""
    a = [
        A("inv", 100e6, 169e6, 300e6, "USD", claim_ids=["c6"], source_url=URL),
        A("cut", 0.1, 0.3, 0.6, "fraction"),
        A("fx", USD_GBP * 0.95, USD_GBP, USD_GBP * 1.05, "GBP/USD", source_note="[FX-USD-GBP]"),
        A("yrs", 0.2, 0.33, 0.5, "1/yr", source_note="spread over 2-5 years"),
        A("ef", SIC28 * 0.6, SIC28, SIC28 * 1.6, "kgCO2e/GBP", source_note="[SIC-28] Machinery"),
        A("kg_t", 0.001, 0.001, 0.001, "t/kg", source_note="unit conversion"),
    ]
    n = [I("i_inv", "inv"), I("i_cut", "cut"), I("i_fx", "fx"), I("i_yrs", "yrs"), I("i_ef", "ef"), I("i_kgt", "kg_t"),
         M("avoided_gbp", "i_inv", "i_cut", "i_fx", unit="GBP"),
         M("value", "avoided_gbp", "i_yrs", unit="GBP/yr"),
         M("impact", "avoided_gbp", "i_yrs", "i_ef", "i_kgt", unit="tCO2e/yr")]
    return ModellerOut(assumptions=a, tree=DriverTree(root_value_id="value", root_impact_id="impact", nodes=n),
                       rationale="r")


def test_currency_parsing():
    assert currencies_in("$169 million") == {"USD": 1}
    assert currencies_in("€20m and £5m") == {"EUR": 1, "GBP": 1}
    assert currencies_in("2 pounds of steel") == {}  # weight, not money
    assert unit_currency("GBP/visit") == {"GBP": 1}
    assert unit_currency("kgCO2e/GBP") == {"GBP": -1}
    assert unit_currency("GBP/USD") == {"GBP": 1, "USD": -1}


def test_correct_model_passes():
    out = good_model()
    assert modeller.problems(out, REFS, CLAIMS) == []


def test_rejects_dollar_claim_labelled_as_pounds():
    # The real SPARETECH failure: $169M entered as GBP.
    out = good_model()
    out.assumptions[0].unit = "GBP"
    with pytest.raises(GuardrailError, match="in USD"):
        check_currency(out, CLAIMS)


def test_rejects_value_root_not_in_gbp():
    out = good_model()
    out.tree.nodes[6].children = ["i_inv", "i_cut"]  # forgot the exchange rate
    with pytest.raises(GuardrailError, match="not GBP"):
        check_currency(out, CLAIMS)


def test_rejects_adding_different_currencies():
    out = good_model()
    out.assumptions.append(A("eur", 1, 2, 3, "EUR"))
    out.tree.nodes.append(I("i_eur", "eur"))
    out.tree.nodes.append(Node(id="mix", label="mix", op="add", children=["avoided_gbp", "i_eur"]))
    out.tree.nodes[7].children = ["mix", "i_yrs"]
    with pytest.raises(GuardrailError, match="different currencies"):
        check_currency(out, CLAIMS)


def test_rejects_invented_emission_factor():
    # The real SPARETECH failure: 0.15 tCO2e per GBP as a judgement call.
    out = good_model()
    out.assumptions[4] = A("ef", 0.05, 0.15, 0.3, "tCO2e/GBP")
    with pytest.raises(GuardrailError, match="cites no row"):
        check_factors(out, REFS)


def test_rejects_factor_that_does_not_match_its_row():
    out = good_model()
    out.assumptions[4].base = 0.9
    out.assumptions[4].high = 1.0
    with pytest.raises(GuardrailError, match="does not match"):
        check_factors(out, REFS)


def test_accepts_factor_in_tonnes():
    out = good_model()
    ef = out.assumptions[4]
    ef.unit, ef.low, ef.base, ef.high = "tCO2e/GBP", ef.low / 1000, ef.base / 1000, ef.high / 1000
    check_factors(out, REFS)


def test_clamps_factor_range_instead_of_failing():
    out = good_model()
    ef = out.assumptions[4]
    ef.low, ef.high = SIC28 * 0.499, SIC28 * 5
    check_factors(out, REFS)
    assert ef.low == pytest.approx(SIC28 * 0.5) and ef.high == pytest.approx(SIC28 * 2)
    assert "range limited" in ef.source_note


def test_rejects_wrong_exchange_rate():
    out = good_model()
    fx = out.assumptions[2]
    fx.low, fx.base, fx.high = 0.9, 1.0, 1.1  # treating dollars as pounds
    with pytest.raises(GuardrailError, match="should be"):
        check_factors(out, REFS)


def test_rejects_uncited_exchange_rate():
    out = good_model()
    out.assumptions[2].source_note = "approx"
    with pytest.raises(GuardrailError, match="table C"):
        check_factors(out, REFS)


def test_company_claimed_emissions_are_left_to_the_sceptic():
    out = good_model()
    out.assumptions[4] = A("ef", 0.1, 0.2, 0.3, "kgCO2e/GBP", claim_ids=["c6"], source_url=URL)
    check_factors(out, REFS)


def test_problems_lists_every_failure_for_one_repair():
    out = good_model()
    out.assumptions[0].unit = "GBP"
    out.assumptions[4] = A("ef", 0.05, 0.15, 0.3, "kgCO2e/GBP")  # invented, uncited
    found = modeller.problems(out, REFS, CLAIMS)
    assert len(found) == 2


def test_attribution_must_feed_both_roots():
    out = good_model()
    out.assumptions.append(A("attr", 0.5, 0.8, 1.0, "fraction", source_note="share caused by the product"))
    out.assumptions[-1].label = "Attribution share"
    out.tree.nodes.append(I("i_attr", "attr"))
    out.tree.nodes[8].children.append("i_attr")  # impact only
    assert any("attribution" in p for p in modeller.problems(out, REFS, CLAIMS))
    out.tree.nodes[6].children.append("i_attr")  # now on the shared driver
    out.tree.nodes[8].children.remove("i_attr")
    assert modeller.problems(out, REFS, CLAIMS) == []


def test_repairs_are_reported(monkeypatch):
    from server import llm
    bad, good = good_model(), good_model()
    bad.assumptions[0].unit = "GBP"
    replies = iter([bad, good])
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: next(replies))
    seen = []
    out = modeller._build("p", REFS, CLAIMS, on_repair=seen.append)
    assert out is good
    assert len(seen) == 1 and "USD" in seen[0][0]


# ---------------------------------------------------------------- units and dead ends

def visits_model(value_children=("i_cost", "visits")):
    """Vyntelligence shape: miles avoided -> visits -> GBP, and the same miles -> tCO2e."""
    a = [
        A("miles", 2e6, 4e6, 8e6, "miles/yr", claim_ids=["c1"], source_url=URL),
        A("attr", 0.3, 0.5, 0.8, "fraction"),
        A("mpv", 10, 20, 40, "miles/visit"),
        A("cost", 50, 100, 200, "GBP/visit"),
        A("ef", 0.3, 0.41, 0.5, "kg CO2e/mile"),
        A("kg_t", 0.001, 0.001, 0.001, "tonnes/kg", source_note="unit conversion"),
    ]
    n = [I("i_miles", "miles"), I("i_attr", "attr"), I("i_mpv", "mpv"), I("i_cost", "cost"),
         I("i_ef", "ef"), I("i_kgt", "kg_t"),
         M("avoided", "i_miles", "i_attr", unit="miles/yr"),
         Node(id="visits", label="Visits avoided", op="divide", children=["avoided", "i_mpv"], unit="visits/yr"),
         M("value", *value_children, unit="GBP/yr"),
         M("impact", "avoided", "i_ef", "i_kgt", unit="tCO2e/yr")]
    return ModellerOut(assumptions=a, tree=DriverTree(root_value_id="value", root_impact_id="impact", nodes=n),
                       rationale="r")


def test_unit_parsing():
    from server.guardrails import unit_dims
    assert unit_dims("kg CO2e/mile") == {"kg": 1, "co2e": 1, "mile": -1}
    assert unit_dims("tonnes/kg") == {"t": 1, "kg": -1}
    assert unit_dims("miles/vehicle/yr") == {"mile": 1, "vehicle": -1, "yr": -1}
    assert unit_dims("% fines reduction") == {}
    assert unit_dims("1/yr") == {"yr": -1}
    assert unit_dims("million carbon miles") is None  # free text: skip, don't guess


def test_correct_visits_model_passes():
    from server.guardrails import check_units
    check_units(visits_model())
    check_units(good_model())


def test_rejects_miles_times_gbp_per_visit():
    # The real Vyntelligence failure: miles x GBP/visit labelled GBP/yr, 20x too high.
    from server.guardrails import check_units
    out = visits_model(value_children=("avoided", "i_cost"))
    with pytest.raises(GuardrailError, match="miles per visit"):
        check_units(out)


def test_rejects_kg_labelled_as_tonnes():
    from server.guardrails import check_units
    out = visits_model()
    out.tree.nodes[-1].children = ["avoided", "i_ef"]  # forgot kg -> t
    with pytest.raises(GuardrailError, match="t/kg"):
        check_units(out)


def test_rejects_step_that_feeds_neither_root():
    out = visits_model(value_children=("avoided", "i_cost"))
    found = modeller.problems(out)
    assert any("feed neither root" in p and "Visits avoided" in p for p in found)
