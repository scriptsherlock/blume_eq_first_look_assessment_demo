You are building the first-look model for an investment team. One model must show two outputs from shared drivers:
1. **Customer value**: annual saving or value created for customers, in GBP per year (unit "GBP/yr").
2. **Impact**: annual emissions avoided, in tonnes CO2e per year (unit "tCO2e/yr").

Where the same mechanism drives both (for example an avoided site visit saves labour cost and van emissions), the two roots must share that driver node. If the company makes no emissions claim, still build the impact root from the physical mechanism and flag the assumptions as judgement calls.

Company: {company}

Claims, verdicts and objections:
{claims}

Emission factors you may cite (UK Government GHG Conversion Factors 2025, Open Government Licence v3.0, {factor_url}):
{factors}

Rules for the tree:
- Nodes have `op` in input, multiply, add, subtract, divide. `input` nodes have no children and point to one assumption via `assumption_id`. `subtract` and `divide` take exactly 2 children in order (a - b, a / b).
- Every input must reference an assumption. Give each node a `unit`.
- Keep it small: 8 to 16 nodes. Name nodes so an investor reads the tree left to right as an argument.
- Convert units explicitly with an assumption node where needed (for example kg to tonnes = 0.001, flagged as a source of "unit conversion").

Rules for assumptions:
- Each has low <= base <= high and a unit.
- If a number comes from a claim, set `claim_ids` and give the page as `source_url`. If it comes from the emission factor table, cite {factor_url} and name the row in `source_note`.
- Anything else is a judgement call: set `judgement_call` true, `source_url` null, and make the low/high range honest and wide.
- Ids a1, a2, ...; node ids n1, n2, ...

In `rationale`, explain in 2 or 3 sentences what the tree assumes and where it is weakest.
