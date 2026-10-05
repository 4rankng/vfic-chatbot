import { describe, expect, it } from "vitest";

import { formatTrendBucket } from "./trendAxis";

describe("formatTrendBucket", () => {
  it("falls back for null and echoes an unparseable bucket back", () => {
    expect(formatTrendBucket(null)).toBe("Chưa có");
    expect(formatTrendBucket("not-a-date")).toBe("not-a-date");
  });

  it("formats bucket timestamps as Vietnamese times", () => {
    expect(formatTrendBucket("2026-07-12T08:30:00+07:00")).toMatch(/08:30/);
  });

  it("includes the date when the window spans multiple days", () => {
    expect(formatTrendBucket("2026-07-12T08:30:00+07:00", true)).toMatch(
      /08:30.*12[-/]07/,
    );
  });
});
