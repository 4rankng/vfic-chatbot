import { formatTrendBucket } from "./trendAxis";
import type { PerfTrendBucket, PerfWindow } from "./usePerformanceStats";

// Vietnamese number formatting for the two metric panels and the trend chart.
// The formatter is shared so the headline value, the plot labels and the
// accessible table cannot drift apart (one decimal, comma separator).
const numberFormatter = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 1,
});

export type TrendRow = {
  label: string;
  p95: number | null;
  p50: number | null;
  turns: number;
};

/** Seconds without a unit, for cells whose header already carries it. */
export const formatSecondsValue = (seconds: number | null): string =>
  seconds == null ? "—" : numberFormatter.format(seconds);

/** A millisecond figure as a labelled Vietnamese duration ("3,2 giây"). */
export const formatMilliseconds = (ms: number | null): string =>
  ms == null ? "—" : `${formatSecondsValue(ms / 1000)} giây`;

/** A 0–100 percentage as "25%" — or a dash when the rate is unknown. */
export const formatPercent = (rate: number | null): string =>
  rate == null ? "—" : `${numberFormatter.format(rate)}%`;

/**
 * Plots the buckets in seconds against the ≤10s target. Long windows are
 * bucketed by day/week, so their axis labels need the date too; `null`
 * milliseconds stay `null` so the line keeps a gap instead of a fake zero.
 */
export const toTrendRows = (
  trend: PerfTrendBucket[],
  window: PerfWindow,
): TrendRow[] => {
  const includeDate = window !== "1d" && window !== "7d";
  return trend.map((bucket) => ({
    label: formatTrendBucket(bucket.bucket, includeDate),
    p95: bucket.p95_ms == null ? null : bucket.p95_ms / 1000,
    p50: bucket.p50_ms == null ? null : bucket.p50_ms / 1000,
    turns: bucket.turns,
  }));
};

/**
 * One tooltip row: the series' seconds plus, on the primary (p95) row only, the
 * bucket's turn count — the volume belongs to the bucket, not to a series.
 */
export const trendTooltipFormatter = (
  value: number | string | ReadonlyArray<number | string> | null | undefined,
  name: number | string | undefined,
  item: { payload?: TrendRow } | undefined,
): [string, string] => {
  const seconds = typeof value === "number" ? value : null;
  const turns = item?.payload?.turns;
  const volume =
    name === "p95" && turns != null
      ? ` · ${turns.toLocaleString("vi-VN")} lượt`
      : "";
  return [`${formatSecondsValue(seconds)} giây${volume}`, String(name ?? "")];
};
