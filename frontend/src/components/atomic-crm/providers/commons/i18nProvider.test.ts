import { afterEach, describe, expect, it, vi } from "vitest";
import {
  assertSupportedRuntimeLocale,
  getInitialLocale,
  i18nProvider,
} from "./i18nProvider";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("i18nProvider", () => {
  it("registers only vi locale", () => {
    expect(i18nProvider.getLocales?.()).toEqual([
      { locale: "vi", name: "Tiếng Việt" },
    ]);
  });

  it("translates keys in Vietnamese", () => {
    expect(i18nProvider.translate("crm.profile.title")).toBe("Hồ sơ cá nhân");
  });

  it("does not inject an English business fallback for missing keys", () => {
    expect(i18nProvider.translate("missing.customer.key")).toBe(
      "missing.customer.key",
    );
  });

  it("always returns vi for getInitialLocale", () => {
    expect(getInitialLocale("vi-VN")).toBe("vi");
  });

  it("rejects a locale whose catalog is not shipped", () => {
    expect(() => assertSupportedRuntimeLocale("en-US")).toThrow(RangeError);
  });
});
