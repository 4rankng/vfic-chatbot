import { afterEach, describe, expect, it, vi } from "vitest";
import { getInitialLocale, i18nProvider } from "./i18nProvider";

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
    expect(i18nProvider.translate("crm.changelog.title")).toBe(
      "Nhật ký thay đổi",
    );
  });

  it("falls back to english catalog for missing keys in vietnamese", () => {
    // crm.action.reset_password isn't in vietnameseCrmMessages, so it falls
    // back to the English catalog value.
    expect(i18nProvider.translate("crm.action.reset_password")).toBe(
      "Reset Password",
    );
  });

  it("always returns vi for getInitialLocale", () => {
    expect(getInitialLocale()).toBe("vi");
  });
});
