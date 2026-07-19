import { describe, expect, it } from "vitest";

import stylesheet from "./settings.css?raw";

describe("mobile settings density", () => {
  it("keeps the page title above compact navigation and section controls", () => {
    expect(stylesheet).toMatch(
      /\.settings-command-header h1[\s\S]*font-size:\s*var\(--fs-page-title\)/,
    );
    expect(stylesheet).toMatch(
      /\.settings-mobile-drawer-trigger[\s\S]*min-height:\s*44px/,
    );
    expect(stylesheet).toMatch(
      /\.settings-mobile-card \.settings-card-header[\s\S]*min-height:\s*48px/,
    );
  });

  it("uses compact visible controls without reducing their effective tap area", () => {
    expect(stylesheet).toMatch(
      /\.settings-input-action::after,[\s\S]*inset:\s*-4px/,
    );
    expect(stylesheet).toMatch(
      /\.settings-test-button::after[\s\S]*inset:\s*-6px/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 479px\)[\s\S]*min-height:\s*44px\s*!important/,
    );
  });

  it("places credentials side by side at tablet-width mobile layouts", () => {
    expect(stylesheet).toMatch(
      /@media \(min-width: 480px\) and \(max-width: 767px\)[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/,
    );
  });
});
