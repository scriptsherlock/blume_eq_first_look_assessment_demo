# First Look Assessment

**Screening, redesigned with AI.** Paste a page about a company. A team of AI agents reads every claim, looks for independent evidence, argues against each claim, and builds a small model of what the product is worth to customers and to the climate. The output is not a summary. It is the questions most worth asking the founder, ranked by how much each answer would change the result.

**Live demo:** https://scriptsherlock.github.io/blume_eq_first_look_assessment_demo/ (saved runs, no key needed)

> Illustrative, public data only. Not Blume Equity's or any company's figures.

## The task it changes

Before a founder call, someone has to decide what to believe about a company and what to ask. Today that usually means rereading a press release, copying numbers into a spreadsheet and guessing the gaps, and the next look at the same company starts again from scratch. Blume tracked CameraMatics and SPARETECH from 2024 before investing in 2026, so most companies get many looks.

| | Today | With First Look Assessment |
|---|---|---|
| Starting point | A blank spreadsheet, every time | Everything learned at earlier looks at this company |
| Claims | Believed, or not, from the page | Quoted word for word, challenged, and given a verdict |
| Unknowns | A fresh guess each time | A labelled estimate with a range, anchored in how similar numbers were sized at other companies |
| Output | A summary of what the company says | Founder questions, ranked by how much each answer matters |
| Between looks | Whatever is in someone's notes | What changed, and which questions are still open |

## What you see

- **Summary:** the two results (customer value in £ a year, carbon avoided in tonnes a year) with their ranges, the founder questions, and every claim with its verdict.
- **Working:** each claim set against the strongest challenge to it, the model as plain equations, and every number with its source or "Estimate" label. Change any number and both results recompute.
- **Map:** a replay of the agents building the assessment step by step.

The example runs use Blume's own posts on Vyntelligence, CameraMatics and SPARETECH. Vyntelligence's post says that *"reducing field visits by 50% saves approximately 4 million carbon miles annually"*. One avoided site visit saves the customer money and avoids van emissions, so the model uses that one driver for both results, and the commercial and climate cases cannot drift apart.

## How it works

Five agents, each with one job. Code checks every step.

| Agent | Job | What code checks |
|---|---|---|
| Reader | Pulls up to 8 claims from the page, each with a quote | The quote must appear word for word on the page, or the claim is dropped |
| Researcher | Plans its own searches, reads the pages it finds, and judges whether each supports or contradicts the claim | It must quote a sentence that code finds on the page. The company's own site doesn't count as independent |
| Sceptic | Argues against each claim and gives a verdict: supported, needs evidence, or not caused by the product | Each objection names the data that would settle it |
| Modeller | Designs the model: one shared driver feeding both results, every number sourced or marked as an estimate with a low, best-guess and high value | Units, currencies, emission factors, exchange rates, and that both results share a driver. A model that fails goes back with the reasons |
| Questioner | Writes up to five founder questions, aimed at the numbers that move the result most | Each question must target a real number in the model |

Plain code, not the AI, does every sum: the results, the ranges, and the ranking of which unknown matters most.

### Checks on the model

- **Units:** each result's unit, worked out from its inputs, must match its label. This caught a model that multiplied miles by £ per visit (20× too high) and one that reported kilograms of CO2e as tonnes (1,000× too high).
- **Currency:** a dollar figure stays in dollars until it is converted at the ECB rate. This caught a run that read "$169 million" as pounds.
- **Emission factors:** any CO2e-per-unit figure must cite a row of the UK government tables below and match it. This caught an invented factor about 300× too high.
- **Exchange rates:** must cite and match the day's ECB reference rates.
- **Structure:** both results share at least one input, credit for causing the effect applies to both or neither, and every step feeds a result.

### Memory (RAG)

Every finished run is saved as records (claims with verdicts, numbers with ranges, founder questions), each with an embedding from `gemini-embedding-001`, stored by company and date. On the next run:

1. **History:** earlier looks at the same company are retrieved and given to the Modeller, which starts from them and cites what it reuses.
2. **Comparables:** for each estimate, the closest numbers from other companies' runs are retrieved by meaning, filtered so that £ matches £ and emission factors match emission factors. The Modeller adjusts its guess or says why this company differs.
3. **Since last look:** code compares this look with the last one (new claims, changed verdicts, ranges that narrowed or widened) and marks founder questions that are still unanswered.

Code checks that the model only cites memories it was actually given. The store is a JSONL file searched directly, which takes milliseconds at a fund's scale. The same interface could sit on a vector database such as pgvector once memory grows to data-room documents.

## Status

- **Saved runs are real agent output** from live runs on Blume's public posts: first looks at Vyntelligence, CameraMatics and SPARETECH, and a second look at Vyntelligence from a later post. On the second look the new page added four claims but answered none of the four earlier questions, so all four come back marked "still open".
- **The saved runs were recorded before web search was reliable,** so most of their claims read "needs evidence". Search now works without a paid key: it tries Bing, Google, Yahoo and DuckDuckGo in turn, because each free engine refuses automated queries some of the time. In new test runs it found outside sources for 3 of the 5 Vyntelligence claims, including a page giving 82%, not 85%, for the fines reduction.
- **Runs on `gemini-3.5-flash-lite`,** retrying when the model is busy. A run that stops at the model step can be finished later without redoing the research.
- **95 Python tests** and a check that the browser and server calculate the same numbers. None need a key.

Next: test on real deals and data-room documents, record founders' answers into memory so questions can be closed with data, and re-record the saved runs with search on.

## Run it

Saved runs only (no key):

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

Live runs need a Gemini key from Google AI Studio:

```bash
cp .env.example .env               # add GEMINI_API_KEY
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m uvicorn server.main:app --port 8000
# then start the web app as above; the start page says "Connected"
```

Save a live run as a replay, or finish one that stopped at the model step:

```bash
.venv/Scripts/python -m scripts.record_replay <url> <name>
.venv/Scripts/python -m scripts.record_replay --resume <run_id> <name>
```

Tests:

```bash
.venv/Scripts/python -m pytest -q
cd web && npm test
```

## Layout

```
server/          FastAPI app, orchestrator, agents, evaluator, checks, memory, search
server/prompts/  the agents' instructions
server/llm.py    the only file that talks to a model provider
factors/         emission-factor tables and the ECB rate snapshot
sources/         saved text of the public pages, so tests can check every quote
scripts/         record or resume a run; rebuild memory from saved runs
web/             React front end; saved runs in web/public/replays
tests/           evaluator, checks, memory, search, replay and orchestrator tests
```

## Data sources

| File | Source | Licence |
|---|---|---|
| `factors/uk_ghg_2025_vehicles.csv` | [UK Government GHG Conversion Factors for Company Reporting 2025](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025): cars, vans and HGVs, kg CO2e per km and per mile | Open Government Licence v3.0 |
| `factors/defra_spend_sic_2023.csv` | [DEFRA / University of Leeds spend-based emission multipliers by SIC code, UK 2023](https://www.gov.uk/government/statistics/uks-carbon-footprint), kg CO2e per £ excluding VAT | Open Government Licence v3.0 |
| `factors/fx_ecb_snapshot.json` | [ECB euro foreign exchange reference rates](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml), refreshed on each live run; the snapshot is used offline and in tests | Published by the ECB for information |
| `sources/*.txt` | Text of public Blume Equity posts, saved 16 November 2026. Each file starts with its URL | Used only to test quotes |

Spend-based multipliers are national averages of supply-chain emissions. They suit a first look, not a reported footprint.

## Why Gemini

The agents run on Gemini Flash-Lite because that was the key available. All model calls go through `server/llm.py`, so switching providers means rewriting one file. The project was built with Claude Code.
