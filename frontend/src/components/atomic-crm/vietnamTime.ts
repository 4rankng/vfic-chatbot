/**
 * Vietnam-time formatting for every recruiter-facing timestamp.
 *
 * The product operates in Vietnam, so a recruiter reads these timestamps to
 * confirm scheduled work actually ran on schedule — the digest status line is
 * there to answer "did tonight's 09:00 send go out?". Answering that in the
 * viewer's own clock silently misreports it: a recruiter in Singapore reads
 * 15:31 for a send that happened at 14:31 Vietnam time, and one in Germany
 * would read a 09:00 Vietnam send as 04:00. So these always render on the
 * Vietnam clock regardless of where the browser is.
 *
 * The trap this module exists to prevent: `toLocaleString("vi-VN")` with no
 * `timeZone` option formats in the RUNTIME's zone. The locale argument only
 * selects the language and the date field order — it does not select a
 * timezone. Always format through these helpers (or build on
 * {@link VIETNAM_TIME_ZONE}) rather than calling `toLocale*` directly.
 */

export const VIETNAM_TIME_ZONE = "Asia/Ho_Chi_Minh";

/**
 * An `Intl.DateTimeFormat` pinned to the Vietnam clock.
 *
 * For sites with bespoke parts (a day key, a chart axis, a weekday label).
 * `dateStyle`/`timeStyle` cannot be combined with explicit parts, so callers
 * pass one or the other.
 */
export function vietnamFormatter(
  options: Intl.DateTimeFormatOptions = {},
): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: VIETNAM_TIME_ZONE,
    ...options,
  });
}

/**
 * Explicit parts, not `dateStyle`/`timeStyle`: `"short"` renders a two-digit
 * year (`6/10/26`), which is wrong for a recruiter reading back a schedule
 * that ran days or weeks ago.
 */
const DATE_TIME = new Intl.DateTimeFormat("vi-VN", {
  timeZone: VIETNAM_TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/**
 * A full recruiter-facing timestamp in Vietnam time, e.g. `14:31:40 06/10/2026`.
 *
 * Returns "" for an absent or unparseable value, so a missing timestamp renders
 * as empty rather than as "Invalid Date".
 */
export function formatVietnamDateTime(
  value: string | Date | null | undefined,
): string {
  if (value == null || value === "") return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return DATE_TIME.format(date);
}
