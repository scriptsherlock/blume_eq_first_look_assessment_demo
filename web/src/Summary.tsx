// The default view: one compact page per company.
// The two outputs sit in a reversed (dark) panel; the top founder question carries the only highlight.
import { useState } from "react";
import type { State } from "./reducer";
import type { Assumption, Diff, Evaluation, Range } from "./types";
import { fmt, STATUS_CLASS } from "./format";
import { shortDate } from "./Card";

const VERDICT_LABEL: Record<string, string> = {
  supported: "Supported",
  "needs evidence": "Needs evidence",
  "not attributable": "Not caused by them",
};

export function Summary({ s, assumptions, ev, onOpen }: {
  s: State;
  assumptions: Assumption[];
  ev?: Evaluation;
  onOpen: (nodeId: string) => void;
}) {
  return (
    <main className="summary">
      <div className="sum-col sum-results">
        <Outputs s={s} assumptions={assumptions} ev={ev} variant="column" />
        <p className="fineprint">{s.label || "Illustrative, public data only."}</p>
      </div>
      <div className="sum-col">
        <Questions s={s} assumptions={assumptions} />
      </div>
      <div className="sum-col summary-side">
        {s.diff && <SinceLastLook diff={s.diff} />}
        <Claims s={s} onOpen={onOpen} />
        {s.notes.length > 0 && (
          <div className="notes">
            {s.notes.map((n) => <p key={n}>{n}</p>)}
          </div>
        )}
      </div>
    </main>
  );
}

// ---------------------------------------------------------------- outputs (reversed panel)

export function Outputs({ s, assumptions, ev, variant = "full", edited = false }: {
  s: State;
  assumptions: Assumption[];
  ev?: Evaluation;
  variant?: "full" | "strip" | "column";
  edited?: boolean;
}) {
  if (!ev) {
    return (
      <section className={`outputs pending ${variant}`}>
        <p>{s.error ? "The run stopped before the model was built." : "Reading the page and testing the claims…"}</p>
      </section>
    );
  }
  const label = (id: string) => assumptions.find((a) => a.id === id)?.label ?? id;
  const drivers = ev.sensitivity.slice(0, 2).map((x) => label(x.assumption_id));
  return (
    <section className={`outputs ${variant}`}>
      <Figure title="Customer value" r={ev.value} />
      <Figure title="Carbon avoided" r={ev.impact} />
      {edited && <p className="outputs-edited">Showing your edited numbers. Reset them in the table below.</p>}
      {drivers.length > 0 && (
        <p className="outputs-why">
          Most of the spread comes from <b>{drivers[0]}</b>
          {drivers[1] && <> and <b>{drivers[1]}</b></>}. The questions are chosen to pin these down.
        </p>
      )}
    </section>
  );
}

function Figure({ title, r }: { title: string; r: Range }) {
  const money = r.unit.startsWith("GBP");
  const [num, per] = money ? splitUnit(fmt(r.base, r.unit)) : [fmt(r.base), prettyUnit(r.unit)];
  return (
    <div className="figure">
      <h2>{title}</h2>
      <div className="figure-value">
        {num}
        {per && <span className="per">{per}</span>}
      </div>
      <RangeBar r={r} />
      <div className="figure-range">
        <span>{money ? fmt(r.low, r.unit) : fmt(r.low)}</span>
        <span>{money ? fmt(r.high, r.unit) : `${fmt(r.high)} ${prettyUnit(r.unit)}`}</span>
      </div>
    </div>
  );
}

function prettyUnit(u: string): string {
  return u.replace("tCO2e", "t CO₂e").replace("/yr", " / yr");
}

function splitUnit(s: string): [string, string] {
  const i = s.indexOf("/");
  return i > 0 ? [s.slice(0, i), s.slice(i)] : [s, ""];
}

// Log scale, because the ranges span orders of magnitude.
function RangeBar({ r }: { r: Range }) {
  const ok = r.low > 0 && r.high > r.low;
  const pos = ok ? (Math.log(r.base) - Math.log(r.low)) / (Math.log(r.high) - Math.log(r.low)) : 0.5;
  return (
    <div className="rangebar" aria-hidden="true">
      <div className="rangebar-track" />
      <div className="rangebar-mark" style={{ left: `${Math.min(100, Math.max(0, pos * 100))}%` }} />
    </div>
  );
}

// ---------------------------------------------------------------- questions

function Questions({ s, assumptions }: { s: State; assumptions: Assumption[] }) {
  const [copied, setCopied] = useState(false);
  const label = (id: string) => assumptions.find((a) => a.id === id)?.label ?? id;
  const email =
    `Hi,\n\nAhead of our next call, it would help to understand a few points:\n\n` +
    s.questions.map((q, i) => `${i + 1}. ${q.text}`).join("\n") +
    `\n\nAny data you can share in advance would be very welcome.\n\nBest regards`;

  return (
    <section className="ask">
      <header className="ask-head">
        <div>
          <h2>Ask the founder</h2>
          <p className="ask-sub">In order: the first answer moves the result most.</p>
        </div>
        {s.questions.length > 0 && (
          <button
            className="btn-quiet"
            onClick={() => {
              navigator.clipboard.writeText(email);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
          >
            {copied ? "Copied" : "Copy as email"}
          </button>
        )}
      </header>
      {s.questions.length === 0 ? (
        <p className="empty">The questions appear once the model is built.</p>
      ) : (
        <ol className="qlist">
          {s.questions.map((q, i) => (
            <li key={q.id} className={i === 0 ? "top" : ""}>
              <p className="q">{q.text}</p>
              <div className="q-meta">
                {q.asked_before && <span className="chip chip-open">Still open from last look</span>}
                <details>
                  <summary>Why ask this</summary>
                  <p><b>{label(q.targets_assumption_id)}.</b> {q.why_it_matters}</p>
                </details>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- since last look

function SinceLastLook({ diff }: { diff: Diff }) {
  const narrowed = diff.assumptions.filter((a) => a.change === "narrowed" || a.became_sourced);
  const moved = diff.assumptions.filter((a) => ["widened", "base moved", "redefined"].includes(a.change));
  const verdicts = diff.claims.filter((c) => c.change === "verdict changed");
  const newClaims = diff.claims.filter((c) => c.change === "new").length;
  const open = diff.questions.filter((q) => q.status === "still open").length;
  const rng = (r?: { low: number; high: number }) => (r ? `${fmt(r.low)}–${fmt(r.high)}` : "");
  const change = (a: Diff["assumptions"][number]) =>
    `${rng(a.before)} → ${rng(a.now)} ${a.now?.unit ?? ""}`;

  return (
    <section className="panel since">
      <header className="panel-head">
        <h2>Since the last look</h2>
        <span className="muted">{shortDate(diff.previous_date)}</span>
      </header>
      <ul className="since-list">
        {open > 0 && <li className="since-open"><b>{open}</b> question{open > 1 ? "s" : ""} still unanswered</li>}
        {newClaims > 0 && <li><b>{newClaims}</b> new claim{newClaims > 1 ? "s" : ""}</li>}
        {narrowed.map((a) => <li key={a.assumption_id}>Narrowed: {a.label} <span className="muted">{change(a)}</span></li>)}
        {moved.map((a) => <li key={a.assumption_id}>Changed: {a.label} <span className="muted">{change(a)}</span></li>)}
        {verdicts.map((c) => <li key={c.text}>Verdict changed: {c.text}</li>)}
        {!open && !newClaims && !narrowed.length && !moved.length && !verdicts.length && <li>Nothing material changed.</li>}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------- claims

function Claims({ s, onOpen }: { s: State; onOpen: (nodeId: string) => void }) {
  if (!s.claims.length) return null;
  return (
    <section className="panel claims">
      <header className="panel-head">
        <h2>What they claim</h2>
        <span className="muted">{s.claims.length}</span>
      </header>
      <ul className="claim-list">
        {s.claims.map((c) => {
          const v = s.verdicts[c.id];
          const evidence = s.evidence.filter((e) => e.claim_id === c.id).length;
          return (
            <li key={c.id}>
              <button className="claim-row" onClick={() => onOpen(`claim:${c.id}`)}>
                <span className={`chip chip-${v ? STATUS_CLASS[v.status] : "pending"}`}>
                  {v ? VERDICT_LABEL[v.status] : "Checking"}
                </span>
                <span className="claim-text">{c.text}</span>
                {evidence > 0 && <span className="muted claim-ev">{evidence} source{evidence > 1 ? "s" : ""}</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
