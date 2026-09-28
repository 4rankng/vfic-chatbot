import { describe, expect, it } from "vitest";

import { i18nProvider } from "./i18nProvider";

// The catalog is the single Vietnamese source for the app, so a key is either
// reachable from a translate()/notify() call or it is dead weight. FE-23
// deleted the subtrees nothing could reach; FE-24 added the keys the settings
// console and the semi-auto takeover now resolve. Both directions are pinned
// here: a live key that stops resolving blanks a button, and a deleted block
// that comes back re-introduces copy nobody maintains.
describe("vietnameseCrmMessages", () => {
  it("resolves the settings-console action labels the sections render", () => {
    expect(i18nProvider.translate("crm.common.save_and_test")).toBe(
      "Lưu & kiểm tra",
    );
    expect(i18nProvider.translate("crm.common.save_credentials")).toBe(
      "Lưu thông tin",
    );
    expect(i18nProvider.translate("crm.common.save_project")).toBe("Lưu dự án");
    expect(i18nProvider.translate("crm.common.save_file")).toBe("Lưu tệp");
  });

  it("resolves the provider footer note shown when nothing is pending", () => {
    expect(i18nProvider.translate("crm.common.token_encrypted_hint")).toBe(
      "Token được mã hoá, không hiển thị lại.",
    );
  });

  it("resolves both semi-auto takeover notifications", () => {
    expect(i18nProvider.translate("conversations.semi_auto.success")).toBe(
      "Đã bật chế độ bán tự động",
    );
    expect(i18nProvider.translate("conversations.semi_auto.error")).toBe(
      "Không thể bật chế độ bán tự động",
    );
  });

  it("resolves the profile copy the page no longer overrides inline", () => {
    expect(i18nProvider.translate("crm.profile.updated")).toBe(
      "Hồ sơ của bạn đã được cập nhật",
    );
    expect(i18nProvider.translate("crm.profile.update_error")).toBe(
      "Đã xảy ra lỗi. Vui lòng thử lại",
    );
  });

  it("keeps the navigation entry the dashboard still renders", () => {
    expect(i18nProvider.translate("crm.navigation.overview")).toBe("Tổng quan");
  });

  it("no longer carries the blocks no component can reach", () => {
    const pruned = [
      "crm.settings.title",
      "crm.settings.sections.branding",
      "crm.theme.dark",
      "crm.auth.welcome_back",
      "crm.navigation.label",
      "crm.navigation.messages",
      "crm.navigation.projects",
      "crm.navigation.settings",
      "crm.navigation.performance",
      "crm.navigation.account",
      "crm.profile.record_not_found",
      "crm.common.copy",
      "crm.common.copied",
      "crm.common.loading",
      "crm.common.load_failed",
      "resources.conversations.takeover.success",
      "resources.conversations.release.error",
      "ra-auth.auth.forgot_password",
    ];

    // A missing key resolves to itself, so every pruned path is unresolvable.
    for (const key of pruned) {
      expect(i18nProvider.translate(key)).toBe(key);
    }
  });
});
