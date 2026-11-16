import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./styles.css";

import { Card, Ctx } from "./Card";
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
    setCursor(0);
    setLive(false);
    setPlaying(true);
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

  if (!started) return <Start onReplay={openReplay} onLive={openLive} />;

  return (
    <ReactFlowProvider>
      <MapView
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
      <div className="start-inner">
        <div className="eyebrow">First-look assessment</div>
        <h1>Evidence Map</h1>
        <p className="lede">
          Paste a company page. Agents pull out every claim, look for independent evidence, argue against it, build
          one model that links customer value to emissions avoided, and end with the five questions most worth asking
          the founder.
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
            placeholder="https://company.com/case-study"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={!serverLive}
          />
          <button disabled={!serverLive || !url}>Run live</button>
        </form>
        <div className="muted small">
          {serverLive === null
            ? "Checking for a local server…"
            : serverLive
              ? "Local server connected. Live runs use Gemini with Google Search."
              : "Live runs need the local server and a Gemini key (see README). Saved runs below work anywhere."}
        </div>
        {err && <div className="error">{err}</div>}

        <h2>Saved runs</h2>
        <div className="replays">
          {replays.map((r) => (
            <button key={r.file} className="replay-card" onClick={() => onReplay(r.file)}>
              <div className="title">{r.name}</div>
              <div className="muted small">{r.blurb}</div>
            </button>
          ))}
        </div>
        <p className="disclaimer">
          Illustrative, public data only; not Blume's or the company's figures.
        </p>
      </div>
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

function MapView({ state: s, live, replay, onHome, onWhatIf }: {
  state: State;
  live: boolean;
  replay: ReplayCtl | null;
  onHome: () => void;
  onWhatIf: (t: string) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, Override>>({});
  const [showQs, setShowQs] = useState(true);

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

  const { nodes, edges } = useMemo(() => buildGraph(s, assumptions, ev, selected), [s, assumptions, ev, selected]);
  const edited = useMemo(() => new Set(Object.keys(overrides)), [overrides]);

  // Re-fit when the graph grows or the right-hand column opens or closes.
  const rf = useReactFlow();
  const sideOpen = !!selected || (showQs && s.questions.length > 0);
  const fitKey = `${nodes.length}|${sideOpen}`;
  const lastFit = useRef("");
  useEffect(() => {
    if (fitKey === lastFit.current) return;
    lastFit.current = fitKey;
    const t = setTimeout(() => rf.fitView({ duration: 500, padding: 0.08 }), 80);
    return () => clearTimeout(t);
  }, [fitKey, rf]);

  return (
    <Ctx.Provider value={{ s, assumptions, ev, edited }}>
      <div className="app">
        <Rail s={s} onHome={onHome} />
        <div className="canvas">
          <div className="banner">
            {s.label || "Illustrative, public data only"}
            {s.mode === "sample" && <span className="pill pill-warn">sample run · hand-authored, not model output</span>}
          </div>
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
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
          <Columns />
          {s.questions.length > 0 && !showQs && !selected && (
            <button className="qs-toggle" onClick={() => setShowQs(true)}>Founder questions ({s.questions.length})</button>
          )}
        </div>
        {selected && (
          <Drawer
            id={selected}
            s={s}
            assumptions={assumptions}
            live={live}
            override={(id, o) => setOverrides((x) => ({ ...x, [id]: o }))}
            reset={(id) => setOverrides(({ [id]: _, ...rest }) => rest)}
            onWhatIf={onWhatIf}
            onClose={() => setSelected(null)}
          />
        )}
        {!selected && s.questions.length > 0 && showQs && (
          <Questions s={s} assumptions={assumptions} onClose={() => setShowQs(false)} />
        )}
        <BottomBar s={s} ev={ev} edited={edited.size > 0} live={live} replay={replay} onWhatIf={onWhatIf} />
      </div>
    </Ctx.Provider>
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
  extractor: "Extractor",
  researcher: "Researcher",
  sceptic: "Sceptic",
  modeller: "Modeller",
  evaluator: "Evaluator",
  questioner: "Questioner",
};

function Rail({ s, onHome }: { s: State; onHome: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  }, [s.steps.length]);
  return (
    <aside className="rail">
      <button className="link" onClick={onHome}>← Evidence Map</button>
      <div className="rail-company">{s.company || "…"}</div>
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
      {s.dropped.length > 0 && (
        <div className="muted small">
          {s.dropped.length} claim(s) dropped: quote not found verbatim on the page.
        </div>
      )}
    </aside>
  );
}

function BottomBar({ s, ev, edited, live, replay, onWhatIf }: {
  s: State;
  ev: State["evaluation"];
  edited: boolean;
  live: boolean;
  replay: ReplayCtl | null;
  onWhatIf: (t: string) => void;
}) {
  const [text, setText] = useState("");
  return (
    <footer className="bottom">
      <div className="headline">
        <div>
          <div className="eyebrow">Customer value</div>
          <div className="mono">{ev ? fmtRange(ev.value.low, ev.value.base, ev.value.high, ev.value.unit) : "—"}</div>
        </div>
        <div>
          <div className="eyebrow">Emissions avoided</div>
          <div className="mono">{ev ? fmtRange(ev.impact.low, ev.impact.base, ev.impact.high, ev.impact.unit) : "—"}</div>
        </div>
        {edited && <span className="pill pill-edit">your edits applied</span>}
      </div>

      <form
        className="whatif"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) onWhatIf(text.trim());
          setText("");
        }}
      >
        <input
          disabled={!live || !s.finished}
          placeholder={live ? "What if only a third of visits are avoidable?" : "What-if needs a live run; edit assumptions by clicking them"}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </form>

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

function Questions({ s, assumptions, onClose }: { s: State; assumptions: Assumption[]; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const label = (id: string) => assumptions.find((a) => a.id === id)?.label ?? id;
  const email =
    `Hi,\n\nThanks for the conversation so far. Ahead of our next call, it would help to understand a few points:\n\n` +
    s.questions.map((q, i) => `${i + 1}. ${q.text}`).join("\n") +
    `\n\nAny data you can share in advance would be very welcome.\n\nBest regards`;
  return (
    <aside className="questions">
      <div className="q-head">
        <div>
          <div className="eyebrow">Next founder call</div>
          <div className="title">Five questions, ranked by how much the answer moves the result</div>
        </div>
        <button className="link" onClick={onClose}>×</button>
      </div>
      <ol>
        {s.questions.map((q) => (
          <li key={q.id}>
            <div>{q.text}</div>
            <div className="muted small">
              Targets “{label(q.targets_assumption_id)}” (sensitivity #{q.sensitivity_rank}). {q.why_it_matters}
            </div>
          </li>
        ))}
      </ol>
      <button
        onClick={() => {
          navigator.clipboard.writeText(email);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "Copied" : "Copy as email"}
      </button>
    </aside>
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
      <div className="eyebrow">{a.judgement_call ? "Judgement call" : "Sourced assumption"}</div>
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
