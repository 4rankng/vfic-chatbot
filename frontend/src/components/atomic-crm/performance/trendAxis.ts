import type { PerfTrendBucket } from "./usePerformanceStats";

export type TrendAxisTick = {
  index: number;
  label: string;
};

const timeFormatter = new Intl.DateTimeFormat("vi-VN", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Ho_Chi_Minh",
});

const dateTimeFormatter = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Ho_Chi_Minh",
});

export const formatTrendBucket = (
  bucket: string | null,
  includeDate = false,
): string => {
  if (!bucket) return "Chưa có";

  const date = new Date(bucket);
  if (Number.isNaN(date.getTime())) return bucket;

  return (includeDate ? dateTimeFormatter : timeFormatter).format(date);
};

export const getTrendAxisTicks = (
  trend: PerfTrendBucket[],
  includeDate = false,
  maxTicks = 5,
): TrendAxisTick[] => {
  if (trend.length === 0) return [];

  const tickCount = Math.min(maxTicks, trend.length);
  const indices = Array.from(
    { length: tickCount },
    (_, tick) => Math.round((tick * (trend.length - 1)) / (tickCount - 1 || 1)),
  );

  return indices.map((index) => ({
    index,
    label: formatTrendBucket(trend[index]?.bucket ?? null, includeDate),
  }));
};
