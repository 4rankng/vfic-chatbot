import { describe, expect, it } from "vitest";

import {
  VIETNAM_TIME_ZONE,
  formatVietnamDateTime,
  vietnamFormatter,
} from "./vietnamTime";

/**
 * The regression these lock: a recruiter-facing timestamp must read on the
 * Vietnam clock, never the viewer's browser clock. The digest status line
 * exists to answer "did tonight's 09:00 send go out?" — answering it in local
 * time silently misreports it by the viewer's UTC offset.
 */
const SENT_AT = "2026-10-06T07:31:40+00:00"; // 14:31:40 in Vietnam

describe("formatVietnamDateTime", () => {
  it("renders the Vietnam wall-clock time, not UTC and not the runtime zone", () => {
    expect(formatVietnamDateTime(SENT_AT)).toBe("14:31:40 06/10/2026");
  });

  it("ignores the host timezone", () => {
    // Same instant, different host: the formatted value must not move. A
    // regression to `toLocaleString("vi-VN")` would return the local hour.
    const asDate = new Date(SENT_AT);
    expect(formatVietnamDateTime(asDate)).toBe(formatVietnamDateTime(SENT_AT));
  });

  it("accepts a Date as well as an ISO string", () => {
    expect(formatVietnamDateTime(new Date(SENT_AT))).toBe(
      formatVietnamDateTime(SENT_AT),
    );
  });

  it("is empty for an absent or unparseable value, never 'Invalid Date'", () => {
    expect(formatVietnamDateTime(null)).toBe("");
    expect(formatVietnamDateTime(undefined)).toBe("");
    expect(formatVietnamDateTime("")).toBe("");
    expect(formatVietnamDateTime("not-a-date")).toBe("");
  });

  it("shifts across the UTC date boundary the way Vietnam does", () => {
    // 18:30Z is 01:30 on the 7th in Vietnam (UTC+7). A host west of Greenwich
    // would render the 6th, and a naive UTC formatter would render "6/10" too.
    expect(formatVietnamDateTime("2026-10-06T18:30:00+00:00")).toBe(
      "01:30:00 07/10/2026",
    );
  });
});

describe("vietnamFormatter", () => {
  it("pins the Vietnam timezone on every formatter it builds", () => {
    const formatted = vietnamFormatter({
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date(SENT_AT));
    expect(formatted).toBe("06/10/2026");
  });

  it("exposes the zone so sites needing another locale still share it", () => {
    expect(VIETNAM_TIME_ZONE).toBe("Asia/Ho_Chi_Minh");
  });
});
