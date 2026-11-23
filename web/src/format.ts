export function fmt(v: number, unit = ""): string {
  if (!isFinite(v)) return "n/a";
  const abs = Math.abs(v);
  let s: string;
  if (abs >= 1e9) s = (v / 1e9).toFixed(1) + "bn";
  else if (abs >= 1e6) s = (v / 1e6).toFixed(1) + "M";
  else if (abs >= 1e4) s = (v / 1e3).toFixed(0) + "k";
  else if (abs >= 100) s = Math.round(v).toLocaleString("en-GB");
  else if (abs >= 1) s = v.toFixed(abs >= 10 ? 1 : 2);
  else if (abs === 0) s = "0";
  else s = v.toPrecision(2);
  if (unit.startsWith("GBP")) return "£" + s + unit.slice(3).replace(/^\//, "/");
  if (unit === "ratio") return (v * 100).toFixed(0) + "%";
  return unit ? `${s} ${unit}` : s;
}

export function fmtRange(low: number, base: number, high: number, unit: string): string {
  return `${fmt(low, unit)} – ${fmt(high, unit)}  (base ${fmt(base, unit)})`;
}

export const STATUS_CLASS: Record<string, string> = {
  supported: "ok",
  "needs evidence": "warn",
  "not attributable": "bad",
};
