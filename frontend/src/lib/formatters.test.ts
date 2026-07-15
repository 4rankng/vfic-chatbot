import { describe, expect, it } from "vitest";

import { formatCurrency, formatDateTime, formatNumber } from "./formatters";

describe("installation-aware formatters", () => {
  it("formats numbers deterministically with an explicit locale", () => {
    expect(formatNumber(1_234_567.5, { locale: "vi-VN" })).toBe("1.234.567,5");
  });

  it("formats currency with an explicit locale and currency", () => {
    const rendered = formatCurrency(1_234_567, {
      locale: "vi-VN",
      currency: "VND",
    });

    expect(rendered.replace(/\u00a0/g, " ")).toBe("1.234.567 ₫");
  });

  it("preserves the configured currency's minor units", () => {
    expect(
      formatCurrency(1.99, { locale: "en-US", currency: "USD" }),
    ).toBe("$1.99");
  });

  it("formats date-time in the explicitly selected timezone", () => {
    expect(
      formatDateTime("2026-01-15T00:30:00.000Z", {
        locale: "vi-VN",
        timezone: "Asia/Ho_Chi_Minh",
      }),
    ).toBe("07:30 15/01/2026");
  });

  it("uses the selected locale's date order instead of a fixed day-first layout", () => {
    expect(
      formatDateTime("2026-01-15T00:30:00.000Z", {
        locale: "en-US",
        timezone: "America/New_York",
      }),
    ).toBe("01/14/2026, 19:30");
  });

  it("rejects missing or empty regional authority instead of using host defaults", () => {
    expect(() => formatNumber(1, { locale: "" })).toThrow();
    expect(() =>
      formatCurrency(1, { locale: "vi-VN", currency: "" }),
    ).toThrow();
    expect(() =>
      formatDateTime("2026-01-15T00:30:00.000Z", {
        locale: "vi-VN",
        timezone: "",
      }),
    ).toThrow();
  });

  it("rejects invalid locale, currency, timezone, and date values", () => {
    expect(() => formatNumber(1, { locale: "not_a_locale" })).toThrow();
    expect(() =>
      formatCurrency(1, { locale: "vi-VN", currency: "INVALID" }),
    ).toThrow();
    expect(() =>
      formatDateTime("2026-01-15T00:30:00.000Z", {
        locale: "vi-VN",
        timezone: "Not/A_Timezone",
      }),
    ).toThrow();
    expect(() =>
      formatDateTime("not-a-date", {
        locale: "vi-VN",
        timezone: "Asia/Ho_Chi_Minh",
      }),
    ).toThrow();
  });
});
