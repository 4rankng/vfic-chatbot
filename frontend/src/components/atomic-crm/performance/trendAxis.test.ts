import { describe, expect, it } from "vitest";

import { formatTrendBucket, getTrendAxisTicks } from "./trendAxis";
import type { PerfTrendBucket } from "./usePerformanceStats";

const trend = Array.from({ length: 12 }, (_, index): PerfTrendBucket => ({
  bucket: `2026-07-12T${String(8 + Math.floor(index / 2)).padStart(2, "0")}:${index % 2 === 0 ? "00" : "30"}:00+07:00`,
  p95_ms: 100,
  p50_ms: 50,
  turns: 1,
  errors: 0,
}));

describe("trend axis", () => {
  it("falls back for null and invalid buckets", () => {
    expect(formatTrendBucket(null)).toBe("Chưa có");
    expect(formatTrendBucket("not-a-date")).toBe("not-a-date");
  });

  it("formats bucket timestamps as Vietnamese times", () => {
    expect(formatTrendBucket("2026-07-12T08:30:00+07:00")).toMatch(/08:30/);
  });

  it("includes dates when the selected window spans multiple days", () => {
    expect(formatTrendBucket("2026-07-12T08:30:00+07:00", true)).toMatch(
      /08:30.*12[-/]07/,
    );
  });

  it("spreads ticks across the full trend, preserving both endpoints", () => {
    const ticks = getTrendAxisTicks(trend);

    expect(ticks).toHaveLength(5);
    expect(ticks[0]?.index).toBe(0);
    expect(ticks.at(-1)?.index).toBe(trend.length - 1);
  });

  it("returns no ticks for empty trends and one tick for a single bucket", () => {
    expect(getTrendAxisTicks([])).toEqual([]);
    expect(getTrendAxisTicks([trend[0]!])).toEqual([
      {
        index: 0,
        label: formatTrendBucket(trend[0]!.bucket),
      },
    ]);
  });
});
