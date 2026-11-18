You are building the first-look model for an investment team. One model must show two outputs from shared drivers:
1. **Customer value**: annual saving or value created for customers, in GBP per year (unit "GBP/yr").
2. **Impact**: annual emissions avoided, in tonnes CO2e per year (unit "tCO2e/yr").

Both roots must be computed from the **same physical driver node** (for example "attributable miles avoided" feeds both "visits avoided -> GBP" and "kg CO2e -> tCO2e"). Do not add a separate input for a quantity you can derive (for example derive visits avoided = miles avoided / miles per visit; do not make "visits avoided" an input). The evaluator rejects trees whose two roots share no input.

Include an **attribution share** (a judgement call between 0 and 1) applied to the shared driver: the fraction of the claimed effect actually caused by the product.

If the company makes no emissions claim, still build the impact root from the physical mechanism and flag the assumptions as judgement calls.

Company: {company}

Claims, verdicts and objections:
{claims}

Reference tables. These are the **only** emission factors and exchange rates you may use. Each row has an id in square brackets.
{references}

Rules for the tree:
- Nodes have `op` in input, multiply, add, subtract, divide. `input` nodes have no children and point to one assumption via `assumption_id`. `subtract` and `divide` take exactly 2 children in order (a - b, a / b).
- Every input must reference an assumption. Give each node a `unit`.
- Keep it small: 8 to 16 nodes. Name nodes so an investor reads the tree left to right as an argument.
- Convert units explicitly with an assumption node where needed (for example kg to tonnes = 0.001 with unit "t/kg", flagged as a judgement call with `source_note` "unit conversion").

Rules for assumptions:
- Each has low <= base <= high and a unit.
- Labels must say exactly what the number is (for example "total across all deployments", not "per deployment", unless the claim says so).
- If a number comes from a claim, set `claim_ids` and give the page as `source_url`.
- **Money.** Put the currency code in every money unit (GBP, USD, EUR...). Enter a claim's number in the currency the claim uses ("$169 million" is USD, not GBP). Convert to GBP with an exchange-rate assumption from table C (unit like "GBP/USD", base = the table value, row id in `source_note`) multiplied into the tree. The value root must come out in GBP/yr. Never add amounts in different currencies.
- **Emission factors.** Every emissions-per-unit assumption must come from table A (activity: per km or mile) or table B (spend: kgCO2e per GBP spent, for goods or services bought or avoided). Use the row's value as the base, put the row id in square brackets in `source_note` (for example "[SIC-28] Machinery and equipment"), and set `source_url` to the table's URL. You may use neighbouring rows for low and high (within half to double the base). Never invent an emission factor or mark one as a judgement call. Spend multipliers are in GBP, so convert other currencies to GBP before applying them.
- **One-off vs annual.** If a saving happens once (for example inventory you no longer need to buy), either spread it over a stated number of years with an assumption, or say in the label that it is one-off. Do not present a one-off amount as per year without that step.
- Anything else is a judgement call: set `judgement_call` true, `source_url` null, and make the low/high range honest and wide.
- Ids a1, a2, ...; node ids n1, n2, ...

In `rationale`, explain in 2 or 3 sentences what the tree assumes and where it is weakest.
