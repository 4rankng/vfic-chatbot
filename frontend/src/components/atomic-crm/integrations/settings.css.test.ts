import { describe, expect, it } from "vitest";

import featureStyles from "../conversations/inbox/features.css?raw";
import messengerSource from "./FacebookMessengerIntegrationPage.tsx?raw";
import settingsSource from "./ZaloIntegrationPage.tsx?raw";
import stylesheet from "./settings.css?raw";
import userStylesheet from "../users/users.css?raw";

describe("flat settings workspace", () => {
  it("defines one scoped density scale for settings components", () => {
    expect(stylesheet).toMatch(
      /\.settings-workspace-content\s*\{[\s\S]*--settings-control-height:\s*38px;[\s\S]*--settings-action-height:\s*36px;[\s\S]*--settings-touch-target:\s*44px;[\s\S]*--settings-mobile-row-height:\s*48px;/,
    );
  });

  it("keeps the page title above compact navigation and touch-safe mobile controls", () => {
    expect(stylesheet).toMatch(
      /\.settings-command-header h1[\s\S]*font-size:\s*var\(--fs-page-title\)/,
    );
    expect(stylesheet).toMatch(
      /\.settings-mobile-drawer-trigger[\s\S]*min-height:\s*44px/,
    );
    expect(stylesheet).toMatch(
      /\.settings-mobile-group \.settings-group-header[\s\S]*min-height:\s*48px/,
    );
  });

  it("uses compact desktop controls and full mobile touch targets", () => {
    expect(stylesheet).toMatch(
      /\.settings-input-action::after,[\s\S]*inset:\s*-4px/,
    );
    expect(stylesheet).toMatch(
      /\.settings-workspace-content \.settings-test-button[\s\S]*min-height:\s*36px\s*!important/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 767px\)[\s\S]*\.settings-workspace-content \.settings-group \.settings-test-button[\s\S]*min-height:\s*44px\s*!important/,
    );
  });

  it("removes inherited collapse padding from mobile settings rows", () => {
    expect(stylesheet).toMatch(
      /\.settings-mobile-group-summary\s*\{[\s\S]*min-height:\s*var\(--settings-mobile-row-height\);[\s\S]*padding:\s*0;/,
    );
  });

  it("keeps mobile Messenger actions content-sized", () => {
    expect(stylesheet).toMatch(
      /\.settings-workspace-content[\s\S]*\.settings-messenger-recovery-form[\s\S]*\.settings-test-button\s*\{[\s\S]*width:\s*max-content;[\s\S]*max-width:\s*100%;/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width:\s*480px\)[\s\S]*\.settings-workspace-content[\s\S]*\.settings-messenger[\s\S]*\.settings-messenger-primary-action\s*\{[\s\S]*width:\s*max-content;/,
    );
  });

  it("keeps embedded mobile user rows compact without hiding metadata", () => {
    expect(userStylesheet).toMatch(
      /@media \(max-width:\s*760px\)[\s\S]*\.user-directory-row\s*\{[\s\S]*row-gap:\s*4px;[\s\S]*min-height:\s*84px;[\s\S]*padding:\s*8px 0;/,
    );
    expect(userStylesheet).toMatch(
      /\.user-directory-meta\s*\{[\s\S]*grid-template-columns:\s*auto auto minmax\(0, 1fr\);/,
    );
  });

  it("renders configuration groups as elevated cards with tinted header bands", () => {
    expect(settingsSource).not.toContain("tt-card");
    expect(messengerSource).not.toContain("tt-card");
    expect(stylesheet).toMatch(/--settings-card-radius:\s*12px;/);
    expect(stylesheet).toMatch(
      /\.settings-group\s*\{[^}]*border:\s*1px solid var\(--settings-border\);[^}]*border-radius:\s*var\(--settings-card-radius\);[^}]*background:\s*var\(--settings-elevated\);/,
    );
    expect(stylesheet).toMatch(
      /\.settings-group:hover\s*\{[^}]*border-color:\s*var\(--border-strong\);/,
    );
    expect(stylesheet).toMatch(
      /@media \(min-width: 768px\)[\s\S]*?\.settings-group-header\s*\{[^}]*background:\s*color-mix\(/,
    );
    expect(stylesheet).toMatch(
      /@media \(min-width: 768px\)[\s\S]*?\.settings-section-panel\s*\{[^}]*gap:\s*var\(--settings-space-4\);/,
    );
    expect(stylesheet).not.toMatch(
      /\.settings-section-panel\s*\{[^}]*border-block/,
    );
    expect(featureStyles).toMatch(
      /\.settings-group\s*\{[\s\S]*background:\s*transparent/,
    );
    expect(settingsSource).toContain("SettingsGroupStatus");
  });

  it("compares provider cards side by side on wide screens", () => {
    expect(stylesheet).toMatch(
      /@media \(min-width: 1121px\)[\s\S]*?\.settings-grid-models\s*\{[\s\S]*?grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/,
    );
    expect(stylesheet).toMatch(
      /\.settings-field-status\s*\{[^}]*width:\s*20px[^}]*height:\s*20px/,
    );
    expect(stylesheet).not.toMatch(
      /\.settings-field-status\s*\{[^}]*border-radius/,
    );
  });

  it("places credentials side by side at tablet-width mobile layouts", () => {
    expect(stylesheet).toMatch(
      /@media \(min-width: 480px\) and \(max-width: 767px\)[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/,
    );
  });
});
