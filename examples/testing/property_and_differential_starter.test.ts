/**
 * Copy-paste TypeScript starter: Property-Based (fast-check) & Differential Tests.
 *
 * Mirrors test_property_and_differential_starter.py with the same 4 patterns:
 *   1. Round-trip property:     decode(encode(x)) === x
 *   2. Idempotency property:    normalize(normalize(x)) === normalize(x)
 *   3. Invariant preservation:  length, ordering, and threshold invariants
 *   4. Differential harness:    legacy(x) === refactored(x) after normalization
 *
 * Run with Vitest + fast-check:
 *   npm i -D vitest fast-check
 *   npx vitest run property_and_differential_starter.test.ts
 */

import fc from "fast-check";
import { describe, expect, it } from "vitest";

// ---------------------------------------------------------------------------
// Example Units Under Test (replace with your own production functions)
// ---------------------------------------------------------------------------

interface RecordItem {
  id: string;
  tags: string[];
  score: number;
}

const encodeRecord = (rec: RecordItem): string => JSON.stringify(rec);
const decodeRecord = (raw: string): RecordItem => JSON.parse(raw) as RecordItem;

const normalizeTag = (raw: string): string =>
  raw
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "-")
    .replace(/^-+|-+$/g, "");

const rankTopK = (scores: number[], k: number): number[] =>
  k <= 0 ? [] : [...scores].sort((a, b) => b - a).slice(0, k);

interface EventItem {
  kind: string;
  weight: number;
}

interface SummaryOutput {
  engine: string;
  totals: Array<{ kind: string; weight: number }>;
}

function legacySummarizeEvents(events: EventItem[]): SummaryOutput {
  const counts = new Map<string, number>();
  for (const ev of events) {
    const kind = normalizeTag(ev.kind);
    if (!kind) continue;
    counts.set(kind, (counts.get(kind) ?? 0) + ev.weight);
  }
  return {
    engine: "legacy-v1",
    totals: Array.from(counts.entries()).map(([kind, weight]) => ({ kind, weight })),
  };
}

function refactoredSummarizeEvents(events: EventItem[]): SummaryOutput {
  const counts: Record<string, number> = Object.create(null) as Record<string, number>;
  for (const ev of events) {
    const kind = normalizeTag(ev.kind);
    if (kind) counts[kind] = (counts[kind] ?? 0) + ev.weight;
  }
  return {
    engine: "refactored-v2",
    totals: Object.keys(counts)
      .sort()
      .map((kind) => ({ kind, weight: counts[kind] })),
  };
}

function normalizeForDiff(out: SummaryOutput): { totals: Array<{ kind: string; weight: number }> } {
  return {
    totals: [...out.totals].sort((a, b) => (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0)),
  };
}

// ---------------------------------------------------------------------------
// Property & Differential Tests
// ---------------------------------------------------------------------------

describe("Property & Differential Test Starter", () => {
  it("1. round-trip: decode(encode(x)) equals x", () => {
    const recordArb = fc.record<RecordItem>({
      id: fc.string({ minLength: 1, maxLength: 32 }),
      tags: fc.array(fc.string({ maxLength: 16 }), { maxLength: 8 }),
      score: fc.integer({ min: -10_000, max: 10_000 }),
    });

    fc.assert(
      fc.property(recordArb, (record) => {
        expect(decodeRecord(encodeRecord(record))).toEqual(record);
      }),
    );
  });

  it("2. idempotency: normalizeTag(normalizeTag(x)) equals normalizeTag(x)", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 64 }), (raw) => {
        const once = normalizeTag(raw);
        expect(normalizeTag(once)).toEqual(once);
      }),
    );
  });

  it("3. invariants: rankTopK preserves length, descending order, and threshold", () => {
    fc.assert(
      fc.property(
        fc.array(fc.integer({ min: -1000, max: 1000 }), { maxLength: 40 }),
        fc.integer({ min: 0, max: 50 }),
        (scores, k) => {
          const top = rankTopK(scores, k);
          expect(top.length).toBe(Math.min(scores.length, k));
          for (let i = 0; i + 1 < top.length; i++) {
            expect(top[i]).toBeGreaterThanOrEqual(top[i + 1]);
          }
          if (top.length > 0 && scores.length > k) {
            const sortedDesc = [...scores].sort((a, b) => b - a);
            expect(Math.min(...top)).toBeGreaterThanOrEqual(sortedDesc[k]);
          }
        },
      ),
    );
  });

  it("4. differential: refactored matches legacy after deterministic normalization", () => {
    const eventArb = fc.record<EventItem>({
      kind: fc.string({ maxLength: 16 }),
      weight: fc.integer({ min: -100, max: 100 }),
    });

    fc.assert(
      fc.property(fc.array(eventArb, { maxLength: 30 }), (events) => {
        const legacyOut = normalizeForDiff(legacySummarizeEvents(events));
        const refactoredOut = normalizeForDiff(refactoredSummarizeEvents(events));
        expect(refactoredOut).toEqual(legacyOut);
      }),
    );
  });
});
