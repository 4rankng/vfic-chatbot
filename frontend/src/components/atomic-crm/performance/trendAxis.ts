import { vietnamFormatter } from "../vietnamTime";

const timeFormatter = vietnamFormatter({
  hour: "2-digit",
  minute: "2-digit",
});

const dateTimeFormatter = vietnamFormatter({
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/**
 * Formats one trend bucket's timestamp for the plot axis, tooltip and the
 * accessible data table. `null` (a bucket the backend could not stamp) reads
 * "Chưa có"; a string the runtime cannot parse is echoed back rather than
 * turned into "Invalid Date".
 */
export const formatTrendBucket = (
  bucket: string | null,
  includeDate = false,
): string => {
  if (!bucket) return "Chưa có";

  const date = new Date(bucket);
  if (Number.isNaN(date.getTime())) return bucket;

  return (includeDate ? dateTimeFormatter : timeFormatter).format(date);
};
