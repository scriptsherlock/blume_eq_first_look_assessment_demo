// "Show the working": the reasoning as a readable page, not a zoomed-out graph.
import { useState } from "react";
import type { State } from "./reducer";
import type { Assumption, Evaluation, TreeNode } from "./types";
import { fmt, STATUS_CLASS } from "./format";
import { shortDate } from "./Card";
import { Outputs } from "./Summary";
import { BestGuess, RangeLine } from "./RangeLine";

type Override = Pick<Assumption, "low" | "base" | "high">;

const VERDICT_LABEL: Record<string, string> = {
  supported: "Supported",
  "needs evidence": "Needs evidence",
  "not attributable": "Not caused by them",
};
const STANCE_LABEL: Record<string, string> = { supports: "Supports", contradicts: "Contradicts", context: "Context" };
const OP: Record<string, string> = { multiply: "×", divide: "÷", add: "+", subtract: "−" };
const AGENT_LABEL: Record<string, string> = {
  extractor: "Reading the page",
  researcher: "Searching for evidence",
  sceptic: "Arguing against",
  modeller: "Building the model",
  evaluator: "Doing the maths",
  questioner: "Writing questions",
  memory: "Checking memory",
};

export function Working({ s, assumptions, ev, edited, override, reset }: {
  s: State;
  assumptions: Assumption[];
  ev?: Evaluation;
  edited: Set<string>;
  override: (id: string, o: Override) => void;
  reset: (id: string) => void;
}) {
  return (
    <main className="working">
      <Outputs s={s} assumptions={assumptions} ev={ev} edited={edited.size > 0} />
      <ClaimsTested s={s} />
      <Model s={s} assumptions={assumptions} ev={ev} edited={edited} override={override} reset={reset} />
      <MemoryUsed s={s} />
      <RunLog s={s} />
      <p className="fineprint">{s.label || "Illustrative, public data only."}</p>
    </main>
  );
}

function isConversion(a: Assumption): boolean {
  return a.low === a.base && a.base === a.high && /conversion/i.test(`${a.label} ${a.source_note ?? ""}`);
}

// ---------------------------------------------------------------- claims

function ClaimsTested({ s }: { s: State }) {
  const searchOff = s.notes.some((n) => n.toLowerCase().includes("search"));
  return (
    <section className="w-section">
      <header className="w-head">
        <h2>The claims, tested</h2>
        <p>Each claim is quoted from the page, checked against other sources, then argued against.</p>
      </header>
      {s.claims.length === 0 && <p className="empty">Reading the page…</p>}
      <div className="claim-rows">
        <div className="claim-row-head" aria-hidden="true">
          <span>What they claim</span><span>Independent evidence</span><span>The sceptic's challenge</span>
        </div>
        {s.claims.map((c) => {
          const v = s.verdicts[c.id];
          const evidence = s.evidence.filter((e) => e.claim_id === c.id);
          const objection = s.objections.filter((o) => o.claim_id === c.id).sort((a, b) => b.severity - a.severity)[0];
          return (
            <article key={c.id} className="claim-card">
              <div>
                <span className={`chip chip-${v ? STATUS_CLASS[v.status] : "pending"}`}>{v ? VERDICT_LABEL[v.status] : "Checking"}</span>
                <p className="cc-claim">{c.text}</p>
                <blockquote className="cc-quote">“{c.quote}”</blockquote>
              </div>
              <div>
                {evidence.length === 0 ? (
                  <p className="cc-none">{v ? (searchOff ? "Not searched: web search was off for this run." : "No independent source found.") : "Searching…"}</p>
                ) : (
                  <ul className="cc-evidence">
                    {evidence.map((e) => (
                      <li key={e.id}>
                        <span className={`chip stance-${e.stance}`}>{STANCE_LABEL[e.stance]}</span>
                        <p>{e.summary}</p>
                        <a href={e.url} target="_blank" rel="noreferrer">{e.publisher || "Source"}</a>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                {objection ? (
                  <>
                    <p className="cc-objection">{objection.text}</p>
                    <p className="cc-settle"><b>Would settle it:</b> {objection.what_would_resolve_it}</p>
                  </>
                ) : (
                  <p className="cc-none">{v ? "No challenge raised." : "Waiting…"}</p>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {s.dropped.length > 0 && (
        <p className="w-note">{s.dropped.length} more claim{s.dropped.length > 1 ? "s were" : " was"} dropped because the quote could not be found word for word on the page.</p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- model

function Model({ s, assumptions, ev, edited, override, reset }: {
  s: State;
  assumptions: Assumption[];
  ev?: Evaluation;
  edited: Set<string>;
  override: (id: string, o: Override) => void;
  reset: (id: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (!s.treeNodes.length) {
    return (
      <section className="w-section">
        <header className="w-head"><h2>The model</h2></header>
        <p className="empty">The model is built once the claims are tested.</p>
      </section>
    );
  }
  const byId = new Map<string, TreeNode>(s.treeNodes.map((n) => [n.id, n]));
  const aById = new Map(assumptions.map((a) => [a.id, a]));
  const name = (id: string) => {
    const n = byId.get(id);
    if (!n) return id;
    return n.op === "input" && n.assumption_id ? aById.get(n.assumption_id)?.label ?? n.label : n.label;
  };
  const ops = s.treeNodes.filter((n) => n.op !== "input");
  const isRoot = (id: string) => id === s.roots.value || id === s.roots.impact;

  // how much each number moves the result, relative to the biggest mover
  const vb = Math.abs(ev?.value.base ?? 1) || 1;
  const ib = Math.abs(ev?.impact.base ?? 1) || 1;
  const score = new Map((ev?.sensitivity ?? []).map((x) => [x.assumption_id, x.value_swing / vb + x.impact_swing / ib]));
  const maxScore = Math.max(1e-9, ...score.values());
  const ordered = [...assumptions].sort((a, b) => (score.get(b.id) ?? 0) - (score.get(a.id) ?? 0));
  const estimates = assumptions.filter((a) => a.judgement_call && !isConversion(a)).length;

  return (
    <section className="w-section">
      <header className="w-head">
        <h2>The model</h2>
        <p>The AI designed these steps; plain code does every sum. One shared number feeds both results.</p>
      </header>

      <ol className="equations">
        {ops.map((n) => {
          const r = ev?.node_values[n.id];
          return (
            <li key={n.id} className={isRoot(n.id) ? "eq-root" : ""}>
              <span className="eq-lhs">{n.label}</span>
              <span className="eq-rhs">
                ={" "}
                {n.children.map((c, i) => (
                  <span key={c}>
                    {i > 0 && <span className="eq-op"> {OP[n.op]} </span>}
                    <span className="eq-term">{name(c)}</span>
                  </span>
                ))}
              </span>
              <span className="eq-val">{r ? fmt(r.base, n.unit) : ""}</span>
            </li>
          );
        })}
      </ol>

      <div className="numbers-head">
        <h3>The numbers it uses</h3>
        <p>
          <span className="chip chip-est">Estimate</span> means no source gave this number, so the model uses a deliberately wide
          range. Each line runs from the lowest to the highest plausible value; the dot is the best guess. {estimates > 0 && <>There {estimates === 1 ? "is" : "are"} {estimates} here. </>}The founder questions target
          the estimates that move the result most. Click a row to try your own range.
        </p>
      </div>

      <div className="numbers" role="table">
        <div className="num-row num-head" role="row">
          <span role="columnheader">Number</span>
          <span role="columnheader">Best guess, and the range it could fall in</span>
          <span role="columnheader">Moves the result</span>
          <span role="columnheader">Where it comes from</span>
        </div>
        {ordered.map((a) => {
          const sc = score.get(a.id) ?? 0;
          const memIds: string[] = Array.from(a.source_note?.match(/mem-[0-9a-f]{8}/g) ?? []);
          const mem = s.memory.find((m) => memIds.includes(m.record.id));
          return (
            <div key={a.id} className={`num-item ${open === a.id ? "open" : ""}`}>
              <button className="num-row" role="row" onClick={() => setOpen(open === a.id ? null : a.id)} aria-expanded={open === a.id}>
                <span className="num-label">
                  {a.label}
                  {edited.has(a.id) && <span className="chip pill-edit">Edited</span>}
                </span>
                <span className="num-range">
                  <BestGuess base={a.base} unit={a.unit} />
                  <RangeLine low={a.low} base={a.base} high={a.high} unit={a.unit} />
                </span>
                <span className="num-bar" aria-label={`moves the result ${Math.round((sc / maxScore) * 100)} out of 100`}>
                  <span style={{ width: `${Math.max(3, (sc / maxScore) * 100)}%` }} />
                </span>
                <span className="num-source">
                  {isConversion(a) ? <span className="chip">Unit conversion</span>
                    : a.judgement_call ? <span className="chip chip-est">Estimate</span> : <span className="chip chip-ok">Sourced</span>}
                  {mem && <span className="muted"> {mem.role === "history" ? "from last look" : `like ${mem.record.company}`}</span>}
                </span>
              </button>
              {open === a.id && <Editor a={a} override={override} reset={reset} />}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Editor({ a, override, reset }: { a: Assumption; override: (id: string, o: Override) => void; reset: (id: string) => void }) {
  const [v, setV] = useState({ low: a.low, base: a.base, high: a.high });
  const valid = v.low <= v.base && v.base <= v.high;
  return (
    <div className="num-editor">
      <p className="ne-source">
        {a.source_url ? <a href={a.source_url} target="_blank" rel="noreferrer">Source</a> : "No source: an estimate."}
        {a.source_note && <> {a.source_note}</>}
      </p>
      <div className="ne-fields">
        {(["low", "base", "high"] as const).map((k) => (
          <label key={k}>
            {k === "base" ? "Base" : k === "low" ? "Low" : "High"}
            <input type="number" step="any" value={v[k]} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} />
          </label>
        ))}
        <button disabled={!valid} onClick={() => override(a.id, v)}>Apply</button>
        <button className="ghost" onClick={() => { reset(a.id); setV({ low: a.low, base: a.base, high: a.high }); }}>Reset</button>
      </div>
      {!valid && <p className="error">Low must be at most base, and base at most high.</p>}
    </div>
  );
}

// ---------------------------------------------------------------- memory and log

function MemoryUsed({ s }: { s: State }) {
  if (!s.memory.length) return null;
  const history = s.memory.filter((m) => m.role === "history" && m.record.kind === "assumption");
  const comps = s.memory.filter((m) => m.role === "comparable");
  const cited = new Set<string>(s.assumptions.flatMap((a) => Array.from(a.source_note?.match(/mem-[0-9a-f]{8}/g) ?? [])));
  return (
    <section className="w-section">
      <header className="w-head">
        <h2>Memory used</h2>
        <p>What the firm already knew: the last look at this company, and how similar numbers were sized elsewhere.</p>
      </header>
      <div className="memory-grid">
        {history.length > 0 && (
          <div className="mem-col">
            <h3>Last look · {shortDate(history[0].record.run_date)}</h3>
            <ul>{history.map((m) => <li key={m.record.id} className={cited.has(m.record.id) ? "used" : ""}>{m.record.summary}</li>)}</ul>
          </div>
        )}
        {comps.length > 0 && (
          <div className="mem-col">
            <h3>Other companies</h3>
            <ul>{comps.map((m) => <li key={m.record.id} className={cited.has(m.record.id) ? "used" : ""}><b>{m.record.company}:</b> {m.record.summary}</li>)}</ul>
          </div>
        )}
      </div>
      <p className="w-note">Highlighted items were used in this model.</p>
    </section>
  );
}

function RunLog({ s }: { s: State }) {
  return (
    <details className="w-section runlog">
      <summary><h2>Run log</h2><span className="muted">{s.steps.length} steps</span></summary>
      <ol>
        {s.steps.map((st) => (
          <li key={st.seq}><b>{AGENT_LABEL[st.agent] ?? st.agent}</b>{st.detail && <> · {st.detail}</>}</li>
        ))}
      </ol>
      {s.notes.map((n) => <p key={n} className="w-note">{n}</p>)}
      {s.error && <p className="error">{s.error}</p>}
    </details>
  );
}
