"""Checks on the Modeller's output beyond tree structure.

1. Currency: every number carries its currency through the tree. The value
   root must come out in GBP and the impact root in no currency. Adding
   USD to GBP, or labelling a dollar claim as pounds, is rejected.
2. Emission factors: any CO2e-per-unit assumption that is not a company
   claim must cite a row from the reference tables, and its base value must
   match that row. Invented factors are rejected.
3. Exchange rates: a currency-to-currency assumption must cite an ECB row
   and match it.

Each failure is a GuardrailError whose message is sent back to the Modeller
as a repair instruction, so it says what to do, not just what is wrong.
"""
from __future__ import annotations

import re
from collections import Counter

from .evaluator import TreeError
from .references import References
from .schema import Assumption, Claim, ModellerOut

CURRENCY_TOKENS = {
    "GBP": "GBP", "£": "GBP",  # not "pounds": in emissions text it can mean weight
    "USD": "USD", "$": "USD", "US$": "USD", "DOLLAR": "USD", "DOLLARS": "USD",
    "EUR": "EUR", "€": "EUR", "EURO": "EUR", "EUROS": "EUR",
    "CHF": "CHF", "SEK": "SEK", "NOK": "NOK", "DKK": "DKK",
}
_TOKEN_RE = re.compile(r"US\$|[£$€]|[A-Za-z]+")
FACTOR_TOLERANCE = 0.01  # base must match the cited row within 1%
FACTOR_RANGE = (0.5, 2.0)  # low/high may span half to double the base
FX_TOLERANCE = 0.02
FX_RANGE = (0.85, 1.15)


class GuardrailError(TreeError):
    pass


def currencies_in(text: str) -> Counter:
    return Counter(CURRENCY_TOKENS[t.upper()] for t in _TOKEN_RE.findall(text or "") if t.upper() in CURRENCY_TOKENS)


def unit_currency(unit: str) -> Counter:
    """Currency exponents of a unit string: 'GBP/visit' -> {GBP: 1}, 'kgCO2e/GBP' -> {GBP: -1}."""
    num, _, den = (unit or "").partition("/")
    v = Counter()
    v.update(currencies_in(num))
    v.subtract(currencies_in(den))
    return Counter({k: n for k, n in v.items() if n})


def _fmt(v: Counter) -> str:
    return " ".join(f"{k}^{n}" if n != 1 else k for k, n in sorted(v.items())) or "no currency"


def check_currency(out: ModellerOut, claims: list[Claim]) -> None:
    by_a = {a.id: a for a in out.assumptions}
    nodes = {n.id: n for n in out.tree.nodes}
    claim_cur = {c.id: currencies_in(f"{c.quote} {c.unit or ''}") for c in claims}

    # 1. A money assumption taken from a claim must keep the claim's currency.
    for a in out.assumptions:
        a_cur = {k for k, n in unit_currency(a.unit).items() if n > 0}
        if not a_cur:
            continue
        for cid in a.claim_ids:
            src = set(claim_cur.get(cid, {}))
            if src and not (a_cur & src):
                raise GuardrailError(
                    f"assumption {a.id} ('{a.label}') takes its number from claim {cid}, which is in "
                    f"{'/'.join(sorted(src))}, but its unit '{a.unit}' says {'/'.join(sorted(a_cur))}. "
                    f"Keep it in {'/'.join(sorted(src))} and add an exchange-rate assumption from table C "
                    f"(for example unit 'GBP/{sorted(src)[0]}') multiplied in the tree."
                )

    # 2. Propagate currency through the tree.
    memo: dict[str, Counter] = {}

    def cur(nid: str) -> Counter:
        if nid in memo:
            return memo[nid]
        n = nodes[nid]
        if n.op == "input":
            v = unit_currency(by_a[n.assumption_id].unit)  # type: ignore[index]
        else:
            kids = [cur(c) for c in n.children]
            if n.op == "multiply":
                v = Counter()
                for k in kids:
                    v.update(k)
            elif n.op == "divide":
                v = Counter(kids[0])
                v.subtract(kids[1])
            else:  # add / subtract need matching currencies
                if any(k != kids[0] for k in kids[1:]):
                    raise GuardrailError(
                        f"node {nid} ('{n.label}') {n.op}s amounts in different currencies "
                        f"({', '.join(_fmt(k) for k in kids)}). Convert them to GBP first with table C."
                    )
                v = Counter(kids[0])
            v = Counter({k: c for k, c in v.items() if c})
        memo[nid] = v
        return v

    value = cur(out.tree.root_value_id)
    if value != Counter({"GBP": 1}):
        raise GuardrailError(
            f"the customer value root comes out in {_fmt(value)}, not GBP. Enter source figures in their own "
            "currency and multiply by an exchange-rate assumption from table C (unit 'GBP/USD', 'GBP/EUR', ...) "
            "so that the value root is in GBP/yr."
        )
    impact = cur(out.tree.root_impact_id)
    if impact:
        raise GuardrailError(
            f"the emissions root still carries {_fmt(impact)}. A spend-based factor is in kgCO2e/GBP, "
            "so multiply it by an amount in GBP (convert other currencies first)."
        )


def _is_emission_factor(a: Assumption) -> bool:
    num, sep, den = a.unit.partition("/")
    return bool(sep) and "co2" in num.lower() and "co2" not in den.lower()


def _scaled_matches(a: Assumption, row_value: float, row_unit: str) -> bool:
    # Accept the row in its own unit, or tonnes instead of kg.
    scales = [1.0]
    if a.unit.lower().lstrip().startswith(("t", "tonne")) and row_unit.lower().startswith("kg"):
        scales.append(0.001)
    return any(abs(a.base - row_value * s) <= FACTOR_TOLERANCE * row_value * s for s in scales)


def _clamp(a: Assumption, lo: float, hi: float) -> None:
    """Keep a table-backed range within lo..hi times its base.

    The base is what matters and is checked strictly; a range that strays a little
    (often just rounding) is pulled in rather than failing the whole model.
    """
    new_low, new_high = max(a.low, a.base * lo), min(a.high, a.base * hi)
    if (new_low, new_high) != (a.low, a.high):
        a.low, a.high = new_low, new_high
        a.source_note = f"{a.source_note or ''} (range limited to {lo}x-{hi}x of the table value)".strip()


def check_factors(out: ModellerOut, refs: References) -> None:
    for a in out.assumptions:
        num, _, den = a.unit.partition("/")
        is_fx = bool(currencies_in(num)) and bool(currencies_in(den)) and "co2" not in a.unit.lower()

        if _is_emission_factor(a):
            if a.claim_ids:
                continue  # the company's own number; the Sceptic deals with it
            rows = [r for r in refs.cited(a.source_note) if not r.id.startswith("FX-")]
            if not rows:
                raise GuardrailError(
                    f"assumption {a.id} ('{a.label}', {a.unit}) is an emission factor but cites no row from "
                    "tables A or B. Pick the closest row and put its id in square brackets in `source_note`, "
                    "for example '[SIC-28]' or '[5_303_3102_9_1]'. Do not invent emission factors."
                )
            if not any(_scaled_matches(a, r.value, r.unit) for r in rows):
                cited = ", ".join(f"{r.id} = {r.value} {r.unit}" for r in rows)
                raise GuardrailError(
                    f"assumption {a.id} ('{a.label}') has base {a.base} {a.unit}, which does not match the row it "
                    f"cites ({cited}). Use the table value as the base (convert kg to t by x0.001 if needed)."
                )
            _clamp(a, *FACTOR_RANGE)
            if not a.source_url:
                a.source_url = rows[0].source_url  # cite the table even if the model left the URL out
            continue

        if is_fx:
            rows = [r for r in refs.cited(a.source_note) if r.id.startswith("FX-")]
            if not rows:
                raise GuardrailError(
                    f"assumption {a.id} ('{a.label}', {a.unit}) is an exchange rate but cites no row from table C. "
                    "Put the row id in `source_note`, for example '[FX-USD-GBP]'."
                )
            r = rows[0]
            if r.unit.replace(" ", "") != a.unit.replace(" ", "") or abs(a.base - r.value) > FX_TOLERANCE * r.value:
                raise GuardrailError(
                    f"assumption {a.id} should be {r.value} {r.unit} (row {r.id}), not {a.base} {a.unit}."
                )
            _clamp(a, *FX_RANGE)
            if not a.source_url:
                a.source_url = r.source_url


def fill_sources(out: ModellerOut, refs: References) -> None:
    """If an assumption cites a table row but leaves `source_url` empty, use the row's URL.

    Runs before the structural checks, which otherwise reject an unsourced assumption
    that is in fact sourced. Whether the number matches the row is checked later.
    """
    for a in out.assumptions:
        if not a.source_url:
            rows = refs.cited(a.source_note)
            if rows:
                a.source_url = rows[0].source_url
                a.judgement_call = False


# ---------------------------------------------------------------- units

DIMENSIONLESS_WORDS = {"", "1", "fraction", "ratio", "%", "percent", "dimensionless", "share", "x", "multiple"}
UNIT_SYNONYMS = {
    "miles": "mile", "mi": "mile", "visits": "visit", "vehicles": "vehicle", "trips": "trip",
    "year": "yr", "years": "yr", "annum": "yr", "y": "yr", "tonne": "t", "tonnes": "t", "tons": "t",
    "kwh": "kwh", "litre": "litre", "litres": "litre", "l": "litre",
}
_UNIT_TOKEN = re.compile(r"^[a-z][a-z0-9]*$")


def unit_dims(unit: str) -> Counter | None:
    """Exponents of each base unit: 'kgCO2e/mile' -> {kg:1, co2e:1, mile:-1}.

    None when the unit is free text the code cannot read reliably; callers then skip the check.
    """
    u = (unit or "").strip().lower()
    if u in DIMENSIONLESS_WORDS or u.startswith(("%", "percent", "fraction", "share of", "x ")):
        return Counter()
    u = u.replace("£", "gbp").replace("co₂e", "co2e").replace(" co2e", "co2e").replace(" per ", "/")
    parts = u.split("/")
    v = Counter()
    for i, part in enumerate(parts):
        for tok in re.split(r"[·*\s]+", part.strip()):
            if not tok:
                continue
            tok = UNIT_SYNONYMS.get(tok, tok)
            if tok in DIMENSIONLESS_WORDS:
                continue
            m = re.fullmatch(r"(kg|t|g)co2e?", tok)
            base = [m.group(1), "co2e"] if m else [CURRENCY_TOKENS.get(tok.upper(), tok)]
            for b in base:
                if not _UNIT_TOKEN.match(b.lower()) or b in {"million", "thousand", "billion", "bn", "m", "k"}:
                    return None
                v[b.lower()] += 1 if i == 0 else -1
    return Counter({k: n for k, n in v.items() if n})


def _fmt_dims(v: Counter) -> str:
    num = [k if n == 1 else f"{k}^{n}" for k, n in sorted(v.items()) if n > 0]
    den = [k if n == -1 else f"{k}^{-n}" for k, n in sorted(v.items()) if n < 0]
    return ("·".join(num) or "1") + ("/" + "/".join(den) if den else "")


def check_units(out: ModellerOut) -> None:
    """Each root's unit, worked out from its inputs, must match the unit it is labelled with.

    Catches a tree that multiplies miles by GBP per visit and calls the answer GBP/yr.
    """
    by_a = {a.id: a for a in out.assumptions}
    nodes = {n.id: n for n in out.tree.nodes}
    memo: dict[str, Counter | None] = {}

    def dims(nid: str) -> Counter | None:
        if nid in memo:
            return memo[nid]
        n = nodes[nid]
        if n.op == "input":
            v = unit_dims(by_a[n.assumption_id].unit)  # type: ignore[index]
        else:
            kids = [dims(c) for c in n.children]
            if any(k is None for k in kids):
                v = None
            elif n.op == "multiply":
                v = Counter()
                for k in kids:
                    v.update(k)
            elif n.op == "divide":
                v = Counter(kids[0])
                v.subtract(kids[1])
            else:
                v = Counter(kids[0])
            if v is not None:
                v = Counter({k: c for k, c in v.items() if c})
        memo[nid] = v
        return v

    hints = {
        "customer value": "turn miles into visits (divide by miles per visit) before multiplying by GBP per visit",
        "carbon": "multiply kgCO2e by a kg-to-tonnes conversion (unit 't/kg', value 0.001) to get tCO2e",
    }
    money = {c.lower() for c in CURRENCY_TOKENS.values()}

    def physical(v: Counter | None) -> Counter | None:  # currencies are check_currency's job
        return None if v is None else Counter({k: n for k, n in v.items() if k not in money})

    for rid, name in ((out.tree.root_value_id, "customer value"), (out.tree.root_impact_id, "carbon")):
        got, want = dims(rid), unit_dims(nodes[rid].unit)
        if got is None or want is None or physical(got) == physical(want):
            continue
        n = nodes[rid]
        parts = ", ".join(f"{c} '{nodes[c].label}' in {_fmt_dims(dims(c)) if dims(c) is not None else nodes[c].unit}"
                          for c in n.children)
        raise GuardrailError(
            f"the {name} root {rid} ('{n.label}') is labelled {n.unit} but its inputs work out to "
            f"{_fmt_dims(got)} ({n.op} of {parts}). Fix the arithmetic so the units cancel: for example, "
            f"{hints[name]}."
        )


def check(out: ModellerOut, refs: References, claims: list[Claim]) -> None:
    check_currency(out, claims)
    check_factors(out, refs)
    check_units(out)
