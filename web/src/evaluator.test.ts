// Parity: the browser evaluator must agree with the Python evaluator's
// recorded output for every saved replay.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { evaluate } from "./evaluator";
import type { Assumption, RunEvent } from "./types";

const dir = join(__dirname, "..", "public", "replays");
const files = readdirSync(dir).filter((f) => f.endsWith(".jsonl"));

describe.each(files)("%s", (file) => {
  const evs: RunEvent[] = readFileSync(join(dir, file), "utf-8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  const rec = evs.filter((e) => e.type === "tree_evaluated").at(-1)!.payload;
  const rev = rec.revision ?? 0;
  const assumptions: Assumption[] = evs
    .filter((e) => e.type === "assumption_added" && (e.payload.revision ?? 0) === rev)
    .map((e) => e.payload.assumption);

  it("matches the Python evaluator", () => {
    const ev = evaluate(rec.tree, assumptions);
    for (const root of ["value", "impact"] as const) {
      expect(ev[root].low).toBeCloseTo(rec.evaluation[root].low, 6);
      expect(ev[root].base).toBeCloseTo(rec.evaluation[root].base, 6);
      expect(ev[root].high).toBeCloseTo(rec.evaluation[root].high, 6);
    }
    expect(ev.sensitivity.map((s) => s.assumption_id)).toEqual(
      rec.evaluation.sensitivity.map((s: { assumption_id: string }) => s.assumption_id),
    );
  });
});
