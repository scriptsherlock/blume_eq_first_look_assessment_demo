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
| Modeller | Designs a driver tree with two roots: customer value (£/yr) and emissions avoided (tCO2e/yr) | Every assumption is sourced or flagged as a judgement call with a low/base/high range; emission factors come from the [UK Government 2025 conversion factors](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025) |
| Evaluator | Computes the tree, the low/high envelope and the sensitivity ranking | Plain code, not the model. Rejects cycles, missing nodes, unsourced assumptions and bad ranges, and gives the Modeller one repair attempt |
| Questioner | Writes five founder questions, ranked by how much each answer moves the result | Each question targets a real assumption |

**The model does the judgement; code does the arithmetic.** On the canvas you can click any claim to see its quote, evidence and objections, edit any assumption and watch both outputs recompute, or, in a live run, type a what-if ("only a third of visits are avoidable") and the Modeller rebuilds the tree.

Every run is saved as an event log. The front end is a pure function of that log, so any run can be replayed exactly, without a key.

## Status

First pass, running on `gemini-3.5-flash-lite`.

- **Saved runs are real agent output.** Vyntelligence and CameraMatics were recorded from live runs on Blume's public posts. All their quotes are checked against the saved page text, and the browser and server evaluators agree on every number.
- **Web search was not available on the key used.** The free Gemini tier gave no Google Search quota, so the Researcher was skipped and every claim was judged without independent evidence. The canvas says so. With a key that has search quota, the Researcher runs automatically.
- **Guardrails added after reading real output:** the value and impact roots must share an input (the Modeller gets one repair attempt otherwise), questions must target different assumptions, and calls retry on rate limits and overload, falling back to `gemini-3.1-flash-lite` if 3.5 stays unavailable.
- **SPARETECH is not shown.** Its run treated a dollar figure as pounds and invented a spend-based emission factor roughly 100x too high, giving millions of tonnes for one company. The next guardrails to add are currency checks and a cited table of spend-based emission factors.
- 30 Python tests and a browser/server evaluator parity test, all runnable without a key.

Not done yet: unit-consistency checks in the evaluator, the currency and spend-factor guardrails above, and a recorded run with web search on.

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
factors/       UK 2025 vehicle emission factors (Open Government Licence v3.0)
sources/       article text of the public pages used in tests
scripts/       record a live run; build the sample replay
web/           React + React Flow canvas; replays in web/public/replays
tests/         evaluator, replay, fetch and orchestrator tests
```

## Why Gemini

The agents run on Gemini Flash-Lite because that is the key I had. All model calls go through `server/llm.py`, so moving to Claude means rewriting that one file. The project itself was built with Claude Code.
