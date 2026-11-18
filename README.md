# Evidence Map

**A first-look assessment, redesigned with AI.** Paste a company page. Agents pull out every claim, look for independent evidence, argue against each claim, build one model that links customer value to emissions avoided, and finish with the five questions most worth asking the founder. It all happens live on a canvas.

> Illustrative, public data only. Not Blume Equity's or any company's figures.

## The task it redesigns

When a pipeline company looks promising, an analyst has to decide what to believe about its claims before the next founder call. Today that means reading a deck and building a spreadsheet by hand. Here, the model does the reading, research, challenge and model design; the analyst checks, edits and decides.

The example is Blume's own post on Vyntelligence, which says that *"reducing field visits by 50% saves approximately 4 million carbon miles annually"*. One avoided site visit saves the customer money and avoids van emissions, so the model uses one shared driver for both outputs.

## How it works

| Agent | Does | Guardrail |
|---|---|---|
| Extractor | Pulls up to 8 claims from the page, each with a quote | A claim is dropped unless its quote is found verbatim on the page |
| Researcher | Searches the web for independent evidence (Gemini + Google Search) | Source links come from search grounding metadata, never from model text; the company's own domain is excluded |
| Sceptic | Raises the strongest objections and gives a verdict: supported, needs evidence, or not attributable | Each objection names the data that would resolve it |
| Modeller | Designs a driver tree with two roots: customer value (£/yr) and emissions avoided (tCO2e/yr) | Every assumption is sourced or flagged as a judgement call with a low/base/high range. Code checks every model (see below) and sends it back with the reasons, up to two times; repairs show on the canvas |
| Evaluator | Computes the tree, the low/high envelope and the sensitivity ranking | Plain code, not the model |
| Questioner | Writes five founder questions, ranked by how much each answer moves the result | Each question targets a real assumption |

### What the checks enforce

- **Structure:** no cycles or missing nodes; every assumption sourced or flagged; low ≤ base ≤ high.
- **One shared driver:** customer value and emissions avoided must both be computed from at least one common input, and an attribution share must apply to both or neither.
- **Currency:** each number's currency is tracked through the tree. A figure taken from a dollar claim must stay in USD and be converted with an exchange-rate assumption; amounts in different currencies cannot be added; the value root must come out in GBP and the emissions root in no currency.
- **Exchange rates:** must cite and match the day's [ECB euro reference rates](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml), converted to GBP (saved snapshot used offline).
- **Emission factors:** any CO2e-per-unit number that is not the company's own claim must cite a row from one of two official tables, and its base must match that row:
  - [UK Government GHG conversion factors 2025](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025) for vehicle activity (per km or mile);
  - [DEFRA / University of Leeds spend-based multipliers, SIC, 2023](https://www.gov.uk/government/statistics/uks-carbon-footprint) for spending on goods and services (kgCO2e per £, excluding VAT).

  Low and high may use neighbouring rows but are kept within half to double the base.

**The model does the judgement; code does the arithmetic.** On the canvas you can click any claim to see its quote, evidence and objections, edit any assumption and watch both outputs recompute, or, in a live run, type a what-if ("only a third of visits are avoidable") and the Modeller rebuilds the tree.

Every run is saved as an event log. The front end is a pure function of that log, so any run can be replayed exactly, without a key.

## Status

First pass, running on `gemini-3.5-flash-lite`.

- **Saved runs are real agent output.** Vyntelligence, CameraMatics and SPARETECH were recorded from live runs on Blume's public posts. Every quote is checked against the saved page text, every final model passes the checks above, and the browser and server evaluators agree on every number.
- **Web search was not available on the key used.** The free Gemini tier gave no Google Search quota, so the Researcher was skipped and every claim was judged without independent evidence. The canvas says so. With a key that has search quota, the Researcher runs automatically.
- **Why the currency and emission-factor checks exist.** An earlier SPARETECH run treated "$169 million" as pounds and invented an emission factor of 0.15 tCO2e per £. DEFRA's figure for machinery is about 0.51 kg per £, so the invented one was roughly 300 times too high, and the run claimed millions of tonnes for one company. With the checks, the same page gives about £20M a year and 10,500 tCO2e a year for an average customer, with the dollar figure converted at the ECB rate and the DEFRA row cited.
- Calls retry on rate limits and overload, falling back to `gemini-3.1-flash-lite` if 3.5 stays unavailable.
- 54 Python tests and a browser/server evaluator parity test, all runnable without a key.

Not done yet: full unit checks beyond currency (miles vs km, kg vs t), and a recorded run with web search on. Spend-based multipliers are national averages of supply-chain emissions, so they suit a first look, not a reported footprint.

## Run it

Static replay only (no key):

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

Live runs need a Gemini key from Google AI Studio:

```bash
cp .env.example .env               # add GEMINI_API_KEY; check the model IDs
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m uvicorn server.main:app --port 8000
# then start the web app as above; the start screen shows "Local server connected"
```

Record a live run as a replay:

```bash
.venv/Scripts/python -m scripts.record_replay <url> <name>
```

Tests:

```bash
.venv/Scripts/python -m pytest -q
cd web && npm test
```

## Layout

```
server/        FastAPI app, orchestrator, agents, prompts, evaluator, run store
server/llm.py  the only file that talks to a model provider
factors/       UK 2025 vehicle factors, DEFRA 2023 spend multipliers, ECB rate snapshot
sources/       article text of the public pages used in tests
scripts/       record a live run; build the sample replay
web/           React + React Flow canvas; replays in web/public/replays
tests/         evaluator, replay, fetch and orchestrator tests
```

## Why Gemini

The agents run on Gemini Flash-Lite because that is the key I had. All model calls go through `server/llm.py`, so moving to Claude means rewriting that one file. The project itself was built with Claude Code.
