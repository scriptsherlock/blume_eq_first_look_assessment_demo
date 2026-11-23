// A one-row forest plot: the line runs from the low to the high estimate,
// the dot is the best guess. Reads without needing to be told what three numbers mean.
import { fmt } from "./format";

function short(v: number, unit: string): string {
  // Units only where they change how the number reads (money, percentages).
  const u = unit.trim().toLowerCase();
  if (unit.startsWith("GBP") || ["ratio", "fraction", "dimensionless", "share"].includes(u)) return fmt(v, unit).replace(/\/.*$/, "");
  return fmt(v);
}

export function RangeLine({ low, base, high, unit, compact = false }: {
  low: number;
  base: number;
  high: number;
  unit: string;
  compact?: boolean;
}) {
  const span = high - low;
  const pos = span > 0 ? (base - low) / span : 0.5;
  const fixed = span === 0;
  return (
    <span className={`rline ${compact ? "compact" : ""} ${fixed ? "fixed" : ""}`}>
      <span className="rl-end">{fixed ? "fixed value" : short(low, unit)}</span>
      <span className="rl-track" aria-hidden="true">
        {!fixed && <span className="rl-span" />}
        <span className="rl-dot" style={{ left: `${Math.min(100, Math.max(0, pos * 100))}%` }} />
      </span>
      <span className="rl-end">{fixed ? "" : short(high, unit)}</span>
    </span>
  );
}

export function BestGuess({ base, unit }: { base: number; unit: string }) {
  return <span className="best">{fmt(base, unit)}</span>;
}
