import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { createContext, useContext } from "react";
import type { CardData } from "./layout";
import type { State } from "./reducer";
import type { Assumption, Evaluation } from "./types";
import { fmt, STATUS_CLASS } from "./format";

export interface CardCtx {
  s: State;
  assumptions: Assumption[];
  ev?: Evaluation;
  edited: Set<string>;
}
export const Ctx = createContext<CardCtx | null>(null);

const OP_SYMBOL: Record<string, string> = { multiply: "×", add: "+", subtract: "−", divide: "÷" };

export function shortDate(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function Card({ data }: NodeProps<Node<CardData>>) {
  const ctx = useContext(Ctx)!;
  const { s, assumptions, ev, edited } = ctx;
  const { kind, refId } = data;
  let body: React.ReactNode = null;
  let cls = `card card-${kind}`;

  if (kind === "source") {
    body = (
      <>
        <div className="eyebrow">Source page</div>
        <div className="title">{s.company || host(s.url)}</div>
        <div className="muted small">{host(s.url)}</div>
      </>
    );
  } else if (kind === "claim") {
    const c = s.claims.find((x) => x.id === refId)!;
    const v = s.verdicts[refId];
    if (v) cls += ` status-${STATUS_CLASS[v.status]}`;
    body = (
      <>
        <div className="eyebrow">
          Claim · {c.kind}
          {v && <span className={`pill pill-${STATUS_CLASS[v.status]}`}>{v.status}</span>}
        </div>
        <div className="text">{c.text}</div>
      </>
    );
  } else if (kind === "evidence") {
    const e = s.evidence.find((x) => x.id === refId)!;
    cls += ` stance-${e.stance}`;
    body = (
      <>
        <div className="eyebrow">Evidence · {e.stance}</div>
        <div className="text small clamp">{e.summary}</div>
        <div className="muted small">{e.publisher}</div>
      </>
    );
  } else if (kind === "objection") {
    const o = s.objections.find((x) => x.id === refId)!;
    body = (
      <>
        <div className="eyebrow">Sceptic · severity {o.severity}/3</div>
        <div className="text small clamp">{o.text}</div>
      </>
    );
  } else if (kind === "memory") {
    const m = s.memory.find((x) => x.record.id === refId)!;
    const r = m.record;
    const cited = assumptions.some((a) => a.source_note?.includes(r.id));
    cls += ` memory-${m.role}${cited ? " cited" : ""}`;
    body = (
      <>
        <div className="eyebrow">
          {m.role === "history" ? `Last look · ${shortDate(r.run_date)}` : `${r.company} · ${shortDate(r.run_date)}`}
          {cited && <span className="pill pill-mem">used</span>}
        </div>
        <div className="text small clamp">{r.summary}</div>
      </>
    );
  } else if (kind === "assumption") {
    const a = assumptions.find((x) => x.id === refId)!;
    const rank = ev?.sensitivity.find((x) => x.assumption_id === refId)?.rank;
    if (a.judgement_call) cls += " judgement";
    if (edited.has(refId)) cls += " edited";
    body = (
      <>
        <div className="eyebrow">
          {a.judgement_call ? "Judgement call" : "Sourced"}
          {rank && <span className="pill">#{rank} sensitivity</span>}
          {edited.has(refId) && <span className="pill pill-edit">edited</span>}
        </div>
        <div className="text small">{a.label}</div>
        <div className="mono small">
          {fmt(a.low, a.unit)} · <b>{fmt(a.base, a.unit)}</b> · {fmt(a.high, a.unit)}
        </div>
      </>
    );
  } else {
    const n = s.treeNodes.find((x) => x.id === refId)!;
    const r = ev?.node_values[refId];
    body =
      kind === "output" ? (
        <>
          <div className="eyebrow">{refId === s.roots.value ? "Customer value" : "Carbon avoided"}</div>
          <div className="big">{r ? fmt(r.base, n.unit) : "…"}</div>
          {r && <div className="mono small">range {fmt(r.low, n.unit)} – {fmt(r.high, n.unit)}</div>}
        </>
      ) : (
        <>
          <div className="op-row">
            <span className="op">{OP_SYMBOL[n.op]}</span>
            <span className="text small">{n.label}</span>
          </div>
          {r && <div className="mono small">{fmt(r.base, n.unit)}</div>}
        </>
      );
  }

  return (
    <div className={cls}>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Left} id="l" />
      {body}
      <Handle type="source" position={Position.Right} />
      <Handle type="target" position={Position.Right} id="r2" />
    </div>
  );
}
