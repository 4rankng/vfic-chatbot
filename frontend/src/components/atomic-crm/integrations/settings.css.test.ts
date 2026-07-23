import { describe, expect, it } from "vitest";

import featureStyles from "../conversations/inbox/features.css?raw";
import messengerSource from "./FacebookMessengerIntegrationPage.tsx?raw";
import settingsSource from "./ZaloIntegrationPage.tsx?raw";
import stylesheet from "./settings.css?raw";

describe("flat settings workspace", () => {
  it("keeps the page title above comfortable navigation and section controls", () => {
    expect(stylesheet).toMatch(
      /\.settings-command-header h1[\s\S]*font-size:\s*var\(--fs-page-title\)/,
    );
    expect(stylesheet).toMatch(
      /\.settings-mobile-drawer-trigger[\s\S]*min-height:\s*44px/,
    );
    expect(stylesheet).toMatch(
      /\.settings-mobile-group \.settings-group-header[\s\S]*min-height:\s*56px/,
    );
  });

  it("uses visible controls with a full 44px action area", () => {
    expect(stylesheet).toMatch(
      /\.settings-input-action::after,[\s\S]*inset:\s*-4px/,
    );
    expect(stylesheet).toMatch(
      /\.settings-workspace-content \.settings-test-button[\s\S]*min-height:\s*44px\s*!important/,
    );
  });

  it("uses divider-based groups instead of nested cards or gradients", () => {
    expect(settingsSource).not.toContain("tt-card");
    expect(messengerSource).not.toContain("tt-card");
    expect(stylesheet).toMatch(
      /\.settings-section-panel\s*\{[\s\S]*border-block:\s*1px solid var\(--settings-border\)/,
    );
    expect(stylesheet).toMatch(
      /\.settings-group\s*\{[\s\S]*border-radius:\s*0[\s\S]*background:\s*transparent/,
    );
    expect(featureStyles).toMatch(
      /\.settings-group\s*\{[\s\S]*background:\s*transparent/,
    );
    expect(settingsSource).toContain("SettingsGroupStatus");
  });

  it("places credentials side by side at tablet-width mobile layouts", () => {
    expect(stylesheet).toMatch(
      /@media \(min-width: 480px\) and \(max-width: 767px\)[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/,
    );
  });
});
