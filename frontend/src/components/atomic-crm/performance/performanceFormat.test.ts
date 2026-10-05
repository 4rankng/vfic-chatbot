import { describe, expect, it } from "vitest";

import {
  formatMilliseconds,
  formatPercent,
  formatSecondsValue,
  toTrendRows,
  trendTooltipFormatter,
} from "./performanceFormat";
import type { PerfTrendBucket } from "./usePerformanceStats";

const trend: PerfTrendBucket[] = [
  {
    bucket: "2026-07-12T08:00:00+07:00",
    p95_ms: 3200,
    p50_ms: 1500,
    turns: 12,
  },
  { bucket: null, p95_ms: null, p50_ms: null, turns: 0 },
];

describe("performance formatters", () => {
  it("renders seconds, durations and rates in Vietnamese", () => {
    expect(formatSecondsValue(3.2)).toBe("3,2");
    expect(formatMilliseconds(3200)).toBe("3,2 giây");
    expect(formatPercent(25)).toBe("25%");
    expect(formatPercent(33.33)).toBe("33,3%");
  });

  it("renders an unknown value as a dash rather than zero", () => {
    expect(formatSecondsValue(null)).toBe("—");
    expect(formatMilliseconds(null)).toBe("—");
    expect(formatPercent(null)).toBe("—");
  });
});

describe("toTrendRows", () => {
  it("converts milliseconds to seconds and keeps unknown points null", () => {
    expect(toTrendRows(trend, "1d")).toEqual([
      { label: "08:00", p95: 3.2, p50: 1.5, turns: 12 },
      { label: "Chưa có", p95: null, p50: null, turns: 0 },
    ]);
  });

  it("stamps the date on buckets of windows bucketed by day or week", () => {
    const [row] = toTrendRows(trend, "1m");

    expect(row?.label).toMatch(/08:00.*12[-/]07/);
  });
});

describe("trendTooltipFormatter", () => {
  const row = toTrendRows(trend, "1d")[0]!;

  it("shows the series in seconds and the bucket volume on the p95 row", () => {
    expect(trendTooltipFormatter(row.p95, "p95", { payload: row })).toEqual([
      "3,2 giây · 12 lượt",
      "p95",
    ]);
    expect(trendTooltipFormatter(row.p50, "p50", { payload: row })).toEqual([
      "1,5 giây",
      "p50",
    ]);
  });

  it("omits the volume when the row or the value is missing", () => {
    expect(trendTooltipFormatter(undefined, "p95", { payload: row })).toEqual([
      "— giây · 12 lượt",
      "p95",
    ]);
    expect(trendTooltipFormatter(row.p95, undefined, undefined)).toEqual([
      "3,2 giây",
      "",
    ]);
  });
});
