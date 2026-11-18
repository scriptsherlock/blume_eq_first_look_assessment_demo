"""Reference tables the Modeller may cite, and the only numbers it may use for
emission factors and exchange rates.

- UK Government GHG conversion factors 2025 (activity-based, per km / mile)
- DEFRA / University of Leeds spend-based multipliers, SIC, 2023 (kgCO2e per GBP)
- ECB euro reference rates, converted to GBP per unit of each currency

Every row has an id. The Modeller must put that id in an assumption's
`source_note`, and the guardrails check the number against the row.
"""
from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import httpx

FACTORS = Path(__file__).resolve().parent.parent / "factors"

VEHICLE_URL = "https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025"
SPEND_URL = "https://www.gov.uk/government/statistics/uks-carbon-footprint"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
FX_SNAPSHOT = FACTORS / "fx_ecb_snapshot.json"
FX_CURRENCIES = ("USD", "EUR", "CHF", "SEK", "NOK", "DKK")


@dataclass
class Row:
    id: str
    value: float  # in the table's own unit
    unit: str  # e.g. "kgCO2e/mile", "kgCO2e/GBP", "GBP/USD"
    label: str
    source_url: str


@dataclass
class References:
    rows: dict[str, Row] = field(default_factory=dict)
    fx_date: str = ""

    def get(self, row_id: str) -> Row | None:
        return self.rows.get(row_id)

    def cited(self, note: str | None) -> list[Row]:
        """Rows whose id appears in a source note, matched as a whole token."""
        if not note:
            return []
        found = []
        for rid, row in self.rows.items():
            if re.search(r"(?<![\w.\-])" + re.escape(rid) + r"(?![\w\-]|\.\d)", note):
                found.append(row)
        return found

    def prompt_block(self) -> str:
        vehicle = [r for r in self.rows.values() if r.source_url == VEHICLE_URL]
        spend = [r for r in self.rows.values() if r.source_url == SPEND_URL]
        fx = [r for r in self.rows.values() if r.id.startswith("FX-")]
        out = [
            f"A. Activity emission factors, UK Government GHG Conversion Factors 2025 ({VEHICLE_URL}):",
            *[f"- [{r.id}] {r.label}: {r.value} {r.unit}" for r in vehicle],
            "",
            f"B. Spend-based emission multipliers, DEFRA / University of Leeds, SIC, UK 2023, "
            f"current prices, excluding VAT ({SPEND_URL}). Average full supply-chain emissions per GBP spent:",
            *[f"- [{r.id}] {r.label}: {r.value} {r.unit}" for r in spend],
            "",
            f"C. Exchange rates, ECB euro reference rates for {self.fx_date}, expressed as GBP per unit ({ECB_URL}):",
            *[f"- [{r.id}] {r.label}: {r.value} {r.unit}" for r in fx],
        ]
        return "\n".join(out)


def _vehicle_rows() -> list[Row]:
    with (FACTORS / "uk_ghg_2025_vehicles.csv").open(encoding="utf-8") as f:
        return [
            Row(id=r["id"], value=float(r["factor_2025"]), unit=f"kgCO2e/{r['unit'].rstrip('s') if r['unit'] == 'miles' else r['unit']}",
                label=f"{r['vehicle']}, {r['size']}, {r['fuel']}, per {r['unit']}", source_url=VEHICLE_URL)
            for r in csv.DictReader(f)
        ]


def _spend_rows() -> list[Row]:
    with (FACTORS / "defra_spend_sic_2023.csv").open(encoding="utf-8") as f:
        return [
            Row(id="SIC-" + r["sic_code"].replace(" ", ""), value=float(r["kgco2e_per_gbp"]), unit="kgCO2e/GBP",
                label=f"SIC {r['sic_code']} {r['category']}", source_url=SPEND_URL)
            for r in csv.DictReader(f)
        ]


def _parse_ecb(xml: str) -> tuple[str, dict[str, float]]:
    root = ET.fromstring(xml)
    date, per_eur = "", {}
    for el in root.iter():
        if "time" in el.attrib:
            date = el.attrib["time"]
        if "currency" in el.attrib:
            per_eur[el.attrib["currency"]] = float(el.attrib["rate"])
    return date, per_eur


def fx_rates(live: bool = True) -> tuple[str, dict[str, float]]:
    """GBP per one unit of each currency. Live from the ECB, else the saved snapshot."""
    data = None
    if live:
        try:
            r = httpx.get(ECB_URL, timeout=8)
            r.raise_for_status()
            date, per_eur = _parse_ecb(r.text)
            if "GBP" in per_eur:
                data = {"date": date, "per_eur": per_eur}
                FX_SNAPSHOT.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except Exception:
            data = None
    if data is None:
        data = json.loads(FX_SNAPSHOT.read_text(encoding="utf-8"))
    per_eur = data["per_eur"]
    gbp = per_eur["GBP"]
    rates = {"EUR": gbp}
    for c in FX_CURRENCIES:
        if c != "EUR" and c in per_eur:
            rates[c] = gbp / per_eur[c]
    return data["date"], rates


def load(live_fx: bool = True) -> References:
    refs = References()
    for row in _vehicle_rows() + _spend_rows():
        refs.rows[row.id] = row
    refs.fx_date, rates = fx_rates(live_fx)
    for cur, v in rates.items():
        refs.rows[f"FX-{cur}-GBP"] = Row(id=f"FX-{cur}-GBP", value=round(v, 6), unit=f"GBP/{cur}",
                                         label=f"GBP per 1 {cur}", source_url=ECB_URL)
    return refs
