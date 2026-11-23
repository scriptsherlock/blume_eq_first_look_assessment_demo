import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, BackgroundVariant, ReactFlow, ReactFlowProvider, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./styles.css";

import { Card, Ctx, shortDate } from "./Card";
import { Outputs, Summary } from "./Summary";
import { Working } from "./Working";
import { buildGraph } from "./layout";
import { fold, type State } from "./reducer";
import { evaluate } from "./evaluator";
import { fmt, fmtRange, STATUS_CLASS } from "./format";
import type { Assumption, RunEvent } from "./types";

const API = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";
const nodeTypes = { card: Card };

interface ReplayEntry {
  file: string;
  name: string;
  blurb: string;
  look?: string;
}

type Override = Pick<Assumption, "low" | "base" | "high">;

export default function App() {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [live, setLive] = useState(false);
  const [started, setStarted] = useState(false);

  const openReplay = useCallback(async (file: string) => {
    const txt = await (await fetch(`replays/${file}`)).text();
    const evs = txt.split("\n").filter(Boolean).map((l) => JSON.parse(l) as RunEvent);
    setEvents(evs);
    setCursor(evs.length);
    setLive(false);
    setPlaying(false);
    setStarted(true);
  }, []);

  const openLive = useCallback(async (url: string) => {
    const r = await fetch(`${API}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
    const { run_id } = await r.json();
    setEvents([]);
    setLive(true);
    setStarted(true);
    listen(run_id, 0, setEvents);
  }, []);

  // replay clock
  useEffect(() => {
    if (live || !playing || cursor >= events.length) {
      if (cursor >= events.length && events.length) setPlaying(false);
      return;
    }
    const prev = events[cursor - 1]?.ts ?? events[0].ts;
    const gap = Math.min(1.6, Math.max(0.05, events[cursor].ts - prev));
    const t = setTimeout(() => setCursor((c) => c + 1), (gap * 1000) / speed);
    return () => clearTimeout(t);
  }, [live, playing, cursor, events, speed]);

  const visible = live ? events : events.slice(0, cursor);
  const state = useMemo(() => fold(visible), [visible]);
  const full = useMemo(() => fold(events), [events]);

  if (!started) return <Start onReplay={openReplay} onLive={openLive} />;

  return (
    <ReactFlowProvider>
      <MapView
        full={full}
        state={state}
        live={live}
        onWhatIf={(text) => whatIf(state.runId, text, events.length, setEvents)}
        replay={
          live
            ? null
            : { cursor, total: events.length, playing, speed, setCursor, setPlaying, setSpeed }
        }
        onHome={() => {
          setStarted(false);
          setEvents([]);
        }}
      />
    </ReactFlowProvider>
  );
}

function listen(runId: string, since: number, setEvents: React.Dispatch<React.SetStateAction<RunEvent[]>>) {
  const es = new EventSource(`${API}/runs/${runId}/events?since=${since}`);
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data) as RunEvent;
    setEvents((xs) => (xs.some((x) => x.seq === ev.seq) ? xs : [...xs, ev]));
    if (ev.type === "run_finished" || ev.type === "error") es.close();
  };
  es.onerror = () => es.close();
}

async function whatIf(runId: string, instruction: string, since: number, setEvents: React.Dispatch<React.SetStateAction<RunEvent[]>>) {
  await fetch(`${API}/runs/${runId}/whatif`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  });
  listen(runId, since, setEvents);
}

// ---------------------------------------------------------------- start

function Start({ onReplay, onLive }: { onReplay: (f: string) => void; onLive: (u: string) => Promise<void> }) {
  const [replays, setReplays] = useState<ReplayEntry[]>([]);
  const [url, setUrl] = useState("");
  const [serverLive, setServerLive] = useState<boolean | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    fetch("replays/index.json").then((r) => r.json()).then(setReplays).catch(() => setReplays([]));
    fetch(`${API}/health`).then((r) => r.json()).then((h) => setServerLive(!!h.live)).catch(() => setServerLive(false));
  }, []);

  return (
    <div className="start">
      <div className="start-main">
        <h1>First Look Assessment</h1>
        <p className="lede">
          Paste a page about a company. Get the questions worth asking its founder, and an honest range for what the
          product is worth to customers and to the climate.
        </p>

        <form
          className="url-form"
          onSubmit={(e) => {
            e.preventDefault();
            setErr("");
            onLive(url).catch((x) => setErr(String(x.message ?? x)));
          }}
        >
          <input
            aria-label="Company page address"
            placeholder="https://company.com/case-study"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={!serverLive}
          />
          <button disabled={!serverLive || !url}>Assess</button>
        </form>
        <p className="status-line">
          {serverLive === null
            ? "Checking for the local server…"
            : serverLive
              ? "Connected. An assessment takes about ten minutes. Press releases and case studies work best."
              : "Live assessments need the local server. Saved runs work anywhere."}
        </p>
        {err && <p className="error">{err}</p>}

        <h2 className="how-title">How it works</h2>
        <ol className="how">
          <li><b>Reads the page.</b> Every claim is quoted word for word, or dropped.</li>
          <li><b>Tests each claim.</b> Searches for independent sources, then argues against it.</li>
          <li><b>Remembers.</b> Starts from earlier looks at the company and similar companies.</li>
          <li><b>Builds the model.</b> The AI designs it; code does every sum.</li>
          <li><b>Asks.</b> Five founder questions, ranked by how much each answer moves the result.</li>
        </ol>

        <div className="shift">
          <div className="shift-before">
            <h2>Today</h2>
            <p>Each look at a company starts from a blank page.</p>
          </div>
          <div className="shift-after">
            <h2>With this</h2>
            <p>Each look starts from the last one and ends in questions for the founder.</p>
          </div>
        </div>
      </div>

      <aside className="start-runs">
        <h2>Saved runs</h2>
        <div className="replays">
          {replays.map((r) => (
            <button key={r.file} className="replay-card" onClick={() => onReplay(r.file)}>
              <span className="rc-name">{r.name}</span>
              {r.look && <span className={`chip ${r.look === "second look" ? "chip-dark" : ""}`}>{r.look}</span>}
              <span className="rc-blurb">{r.blurb}</span>
            </button>
          ))}
        </div>
        <p className="fineprint">Illustrative, public data only. Not Blume's or the company's figures.</p>
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------- map

interface ReplayCtl {
  cursor: number;
  total: number;
  playing: boolean;
  speed: number;
  setCursor: (n: number) => void;
  setPlaying: (b: boolean) => void;
  setSpeed: (n: number) => void;
}

function MapView({ full: s, state: sm, live, replay, onHome, onWhatIf }: {
  full: State;
  state: State;
  live: boolean;
  replay: ReplayCtl | null;
  onHome: () => void;
  onWhatIf: (t: string) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, Override>>({});
  const [view, setView] = useState<View>("summary");
  const openNode = (_id: string) => setView("working");

  useEffect(() => setOverrides({}), [s.revision, s.runId]);

  const assumptions = useMemo(
    () => s.assumptions.map((a) => (overrides[a.id] ? { ...a, ...overrides[a.id] } : a)),
    [s.assumptions, overrides],
  );
  const ev = useMemo(() => {
    if (!s.tree) return undefined;
    if (!Object.keys(overrides).length) return s.evaluation;
    try {
      return evaluate(s.tree, assumptions);
    } catch {
      return s.evaluation;
    }
  }, [s.tree, s.evaluation, assumptions, overrides]);

  const mapAssumptions = useMemo(
    () => sm.assumptions.map((a) => (overrides[a.id] ? { ...a, ...overrides[a.id] } : a)),
    [sm.assumptions, overrides],
  );
  const mapEv = useMemo(() => {
    if (!sm.tree) return undefined;
    if (!Object.keys(overrides).length) return sm.evaluation;
    try {
      return evaluate(sm.tree, mapAssumptions);
    } catch {
      return sm.evaluation;
    }
  }, [sm.tree, sm.evaluation, mapAssumptions, overrides]);
  const { nodes, edges } = useMemo(() => buildGraph(sm, mapAssumptions, mapEv, selected), [sm, mapAssumptions, mapEv, selected]);

  // Opening the Map plays the run from the start, so you watch it being built.
  useEffect(() => {
    if (view === "map" && replay) {
      replay.setCursor(0);
      replay.setPlaying(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);
  const edited = useMemo(() => new Set(Object.keys(overrides)), [overrides]);

  // Re-fit when the graph grows, the run finishes, the view changes, or the right-hand column opens or closes.
  // Debounced so it runs once the stream pauses and React Flow has measured the new cards.
  const rf = useReactFlow();
  const sideOpen = !!selected;
  const fitKey = `${nodes.length}|${sideOpen}|${s.finished}|${view}`;
  useEffect(() => {
    const t = setTimeout(() => {
      requestAnimationFrame(() => rf.fitView({ duration: 300, padding: 0.08 }));
    }, 350);
    return () => clearTimeout(t);
  }, [fitKey, rf]);

  return (
    <Ctx.Provider value={view === "map" ? { s: sm, assumptions: mapAssumptions, ev: mapEv, edited } : { s, assumptions, ev, edited }}>
      <div className={`app view-${view}`}>
        <TopBar s={s} view={view} setView={setView} onHome={onHome} />
        {view === "summary" ? (
          <Summary s={s} assumptions={assumptions} ev={ev} onOpen={openNode} />
        ) : view === "working" ? (
          <Working
            s={s}
            assumptions={assumptions}
            ev={ev}
            edited={edited}
            override={(id, o) => setOverrides((x) => ({ ...x, [id]: o }))}
            reset={(id) => setOverrides(({ [id]: _, ...rest }) => rest)}
          />
        ) : (
          <>
            <Rail s={sm} />
            <div className="canvas">
              <div className="map-results">
                <Outputs s={sm} assumptions={mapAssumptions} ev={mapEv} variant="strip" edited={edited.size > 0} />
              </div>
              <div className="flow-wrap">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodeClick={(_, n) => setSelected(n.id)}
                onPaneClick={() => setSelected(null)}
                nodesDraggable={false}
                nodesConnectable={false}
                minZoom={0.15}
                fitView
              >
                <Background variant={BackgroundVariant.Dots} gap={24} size={1} />
              </ReactFlow>
              <Columns />
              </div>
            </div>
            {selected && (
              <Drawer
                id={selected}
                s={sm}
                assumptions={mapAssumptions}
                live={live}
                override={(id, o) => setOverrides((x) => ({ ...x, [id]: o }))}
                reset={(id) => setOverrides(({ [id]: _, ...rest }) => rest)}
                onWhatIf={onWhatIf}
                onClose={() => setSelected(null)}
              />
            )}
          </>
        )}
        {(view === "map" || live) && (
          <BottomBar s={s} ev={ev} edited={edited.size > 0} live={live} replay={view === "map" ? replay : null} onWhatIf={onWhatIf} compact />
        )}
      </div>
    </Ctx.Provider>
  );
}

type View = "summary" | "working" | "map";

function TopBar({ s, view, setView, onHome }: {
  s: State;
  view: View;
  setView: (v: View) => void;
  onHome: () => void;
}) {
  const followUp = s.memory.some((m) => m.role === "history");
  const status = s.error
    ? "Stopped"
    : s.finished
      ? "Finished"
      : s.activeAgent
        ? (AGENT_LABEL[s.activeAgent] ?? s.activeAgent)
        : "Starting";
  return (
    <header className="topbar">
      <button className="back" onClick={onHome} aria-label="Back to all runs">&larr;</button>
      <div className="tb-title">
        <h1>{s.company || "Reading the page"}</h1>
        <span className="tb-look">{followUp ? "Follow-up look" : "First look"}</span>
      </div>
      <span className={`tb-status ${s.finished ? "" : "live"}`}>{status}</span>
      <div className="seg" role="tablist" aria-label="View">
        <button role="tab" aria-selected={view === "summary"} onClick={() => setView("summary")}>Summary</button>
        <button role="tab" aria-selected={view === "working"} onClick={() => setView("working")}>Working</button>
        <button role="tab" aria-selected={view === "map"} onClick={() => setView("map")}>Map</button>
      </div>
    </header>
  );
}

function Columns() {
  return (
    <div className="columns-legend">
      <span>Source</span><span>Claims</span><span>Evidence &amp; objections</span><span>Assumptions</span><span>Model → outputs</span>
    </div>
  );
}

const AGENT_LABEL: Record<string, string> = {
  extractor: "Reading the page",
  researcher: "Searching for evidence",
  sceptic: "Arguing against",
  modeller: "Building the model",
  evaluator: "Doing the maths",
  questioner: "Writing questions",
  memory: "Checking memory",
};

function Rail({ s }: { s: State }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  }, [s.steps.length]);
  return (
    <aside className="rail">
      <h2 className="rail-title">What the agents did</h2>
      <div className="rail-steps" ref={ref}>
        {s.steps.map((st) => (
          <div key={st.seq} className={`step ${st.done ? "done" : "active"}`}>
            <div className="step-agent">{AGENT_LABEL[st.agent] ?? st.agent}</div>
            {st.detail && <div className="step-detail">{st.detail}</div>}
          </div>
        ))}
        {s.finished && !s.error && <div className="step done"><div className="step-agent">Done</div></div>}
        {s.error && <div className="error small">{s.error}</div>}
      </div>
      {s.notes.map((n) => (
        <div key={n} className="note small">{n}</div>
      ))}
      {s.dropped.length > 0 && (
        <div className="muted small">
          {s.dropped.length} claim(s) dropped: quote not found verbatim on the page.
        </div>
      )}
    </aside>
  );
}

function BottomBar({ s, ev, edited, live, replay, onWhatIf, compact }: {
  s: State;
  ev: State["evaluation"];
  edited: boolean;
  live: boolean;
  replay: ReplayCtl | null;
  onWhatIf: (t: string) => void;
  compact: boolean;
}) {
  const [text, setText] = useState("");
  return (
    <footer className="bottom">
      {!compact && (
        <div className="headline">
          <div>
            <span className="hl-label">Customer value</span>
            <span className="hl-value">{ev ? fmtRange(ev.value.low, ev.value.base, ev.value.high, ev.value.unit) : "—"}</span>
          </div>
          <div>
            <span className="hl-label">Carbon avoided</span>
            <span className="hl-value">{ev ? fmtRange(ev.impact.low, ev.impact.base, ev.impact.high, ev.impact.unit) : "—"}</span>
          </div>
          {edited && <span className="pill pill-edit">Your edits applied</span>}
        </div>
      )}

      {live && <form
        className="whatif"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) onWhatIf(text.trim());
          setText("");
        }}
      >
        <input
          disabled={!live || !s.finished}
          placeholder={live ? "Ask a what-if, e.g. only a third of visits are avoidable" : "What-ifs need a live run"}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </form>}

      {replay && (
        <div className="replay-ctl">
          <button onClick={() => {
            if (replay.cursor >= replay.total) replay.setCursor(0);
            replay.setPlaying(!replay.playing);
          }}>
            {replay.playing ? "Pause" : replay.cursor >= replay.total ? "Replay" : "Play"}
          </button>
          <button className={replay.speed === 4 ? "on" : ""} onClick={() => replay.setSpeed(replay.speed === 1 ? 4 : 1)}>
            {replay.speed}×
          </button>
          <input
            type="range"
            min={0}
            max={replay.total}
            value={replay.cursor}
            onChange={(e) => {
              replay.setPlaying(false);
              replay.setCursor(Number(e.target.value));
            }}
          />
        </div>
      )}
    </footer>
  );
}

function Drawer({ id, s, assumptions, live, override, reset, onWhatIf, onClose }: {
  id: string;
  s: State;
  assumptions: Assumption[];
  live: boolean;
  override: (id: string, o: Override) => void;
  reset: (id: string) => void;
  onWhatIf: (t: string) => void;
  onClose: () => void;
}) {
  const [kind, ref] = id.split(":");
  let body: React.ReactNode = null;

  if (kind === "claim") {
    const c = s.claims.find((x) => x.id === ref)!;
    const v = s.verdicts[ref];
    body = (
      <>
        <div className="eyebrow">Claim · {c.kind}</div>
        <h3>{c.text}</h3>
        <blockquote>“{c.quote}”</blockquote>
        <a href={c.source_url} target="_blank" rel="noreferrer" className="small">Source page ↗</a>
        {v && (
          <div className={`verdict pill-${STATUS_CLASS[v.status]}`}>
            <b>{v.status}</b> — {v.reason}
          </div>
        )}
        <h4>Evidence</h4>
        {s.evidence.filter((e) => e.claim_id === ref).map((e) => (
          <div key={e.id} className="item">
            <span className={`pill stance-${e.stance}`}>{e.stance}</span> {e.summary}{" "}
            <a href={e.url} target="_blank" rel="noreferrer">{e.publisher || "link"} ↗</a>
            {e.quote && <blockquote className="small">“{e.quote}”</blockquote>}
          </div>
        ))}
        {!s.evidence.some((e) => e.claim_id === ref) && <div className="muted small">No independent evidence found.</div>}
        <h4>Objections</h4>
        {s.objections.filter((o) => o.claim_id === ref).map((o) => (
          <div key={o.id} className="item">
            <div>{o.text}</div>
            <div className="muted small">To resolve: {o.what_would_resolve_it}</div>
          </div>
        ))}
      </>
    );
  } else if (kind === "evidence") {
    const e = s.evidence.find((x) => x.id === ref)!;
    body = (
      <>
        <div className="eyebrow">Evidence · {e.stance}</div>
        <p>{e.summary}</p>
        {e.quote && <blockquote>“{e.quote}”</blockquote>}
        <a href={e.url} target="_blank" rel="noreferrer">{e.publisher || e.url} ↗</a>
      </>
    );
  } else if (kind === "objection") {
    const o = s.objections.find((x) => x.id === ref)!;
    body = (
      <>
        <div className="eyebrow">Sceptic · severity {o.severity}/3</div>
        <p>{o.text}</p>
        <h4>What would resolve it</h4>
        <p>{o.what_would_resolve_it}</p>
      </>
    );
  } else if (kind === "assumption") {
    const a = assumptions.find((x) => x.id === ref)!;
    body = <AssumptionEditor key={ref} a={a} live={live} override={override} reset={reset} onWhatIf={onWhatIf} />;
  } else if (kind === "tree") {
    const n = s.treeNodes.find((x) => x.id === ref)!;
    body = (
      <>
        <div className="eyebrow">Model node · {n.op}</div>
        <h3>{n.label}</h3>
        <div className="muted small">Unit: {n.unit}</div>
        {s.rationale && (
          <>
            <h4>Modeller's rationale</h4>
            <p>{s.rationale}</p>
          </>
        )}
      </>
    );
  } else if (kind === "memory") {
    const m = s.memory.find((x) => x.record.id === ref)!;
    const r = m.record;
    const usedBy = assumptions.filter((a) => a.source_note?.includes(r.id));
    const a = r.data.assumption;
    const v = r.data.verdict;
    body = (
      <>
        <div className="eyebrow">
          {m.role === "history" ? "Memory · earlier look at this company" : `Memory · comparable from ${r.company}`}
        </div>
        <h3>{r.kind === "assumption" && a ? a.label : r.text}</h3>
        {a && <div className="mono small">{fmt(a.low, a.unit)} · <b>{fmt(a.base, a.unit)}</b> · {fmt(a.high, a.unit)}</div>}
        {a?.source_note && <p className="small">{a.source_note}</p>}
        {v?.status && <div className={`verdict pill-${STATUS_CLASS[v.status]}`}><b>{v.status}</b> — {v.reason}</div>}
        <p className="muted small">
          From the {r.company} assessment on {shortDate(r.run_date)}
          {m.score != null && <> · similarity {m.score.toFixed(2)}{m.for_label ? ` to “${m.for_label}”` : ""}</>}
        </p>
        <a href={r.source_url} target="_blank" rel="noreferrer" className="small">Page assessed then ↗</a>
        <h4>Used by</h4>
        {usedBy.length ? usedBy.map((u) => (
          <div key={u.id} className="item"><b>{u.label}</b><div className="muted small">{u.source_note}</div></div>
        )) : <div className="muted small">Shown to the Modeller; not cited in the final model.</div>}
      </>
    );
  } else if (kind === "source") {
    body = (
      <>
        <div className="eyebrow">Source page</div>
        <a href={s.url} target="_blank" rel="noreferrer">{s.url}</a>
        {s.note && <p className="muted">{s.note}</p>}
      </>
    );
  }

  return (
    <aside className="drawer">
      <button className="link close" onClick={onClose}>×</button>
      {body}
    </aside>
  );
}

function AssumptionEditor({ a, live, override, reset, onWhatIf }: {
  a: Assumption;
  live: boolean;
  override: (id: string, o: Override) => void;
  reset: (id: string) => void;
  onWhatIf: (t: string) => void;
}) {
  const [v, setV] = useState({ low: a.low, base: a.base, high: a.high });
  const valid = v.low <= v.base && v.base <= v.high;
  return (
    <>
      <div className="eyebrow">{a.judgement_call ? "Estimate: no source gave this number" : "Sourced"}</div>
      <h3>{a.label}</h3>
      <div className="muted small">Unit: {a.unit}</div>
      {a.source_url && <a href={a.source_url} target="_blank" rel="noreferrer" className="small">Source ↗</a>}
      {a.source_note && <p className="small">{a.source_note}</p>}
      <div className="editor">
        {(["low", "base", "high"] as const).map((k) => (
          <label key={k}>
            {k}
            <input type="number" step="any" value={v[k]} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} />
          </label>
        ))}
      </div>
      <div className="muted small">Current: {fmt(a.low, a.unit)} · {fmt(a.base, a.unit)} · {fmt(a.high, a.unit)}</div>
      {!valid && <div className="error small">Needs low ≤ base ≤ high.</div>}
      <div className="row">
        <button disabled={!valid} onClick={() => override(a.id, v)}>Apply</button>
        <button className="ghost" onClick={() => reset(a.id)}>Reset</button>
      </div>
      <button
        className="ghost danger"
        disabled={!live}
        title={live ? "" : "Rejecting asks the Modeller to rebuild, which needs a live run"}
        onClick={() =>
          onWhatIf(`The analyst rejects assumption ${a.id} ("${a.label}"). Replace it with a more defensible alternative or restructure that branch, and explain why.`)
        }
      >
        Reject and ask the Modeller to rebuild
      </button>
      <p className="muted small">Edits recompute in your browser with the same arithmetic as the server. The model's structure stays the same.</p>
    </>
  );
}
