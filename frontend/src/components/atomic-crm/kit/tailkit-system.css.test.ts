import { describe, expect, it } from "vitest";

import stylesheet from "./tailkit-system.css?raw";

describe("Tailkit action sizing system", () => {
  it("uses one compact desktop hierarchy and preserves mobile touch targets", () => {
    expect(stylesheet).toMatch(/--tt-size:\s*1\.75rem/);
    expect(stylesheet).toMatch(/--tt-size:\s*2rem/);
    expect(stylesheet).toMatch(/--tt-size:\s*2\.25rem/);
    expect(stylesheet).toMatch(/font-size:\s*var\(--fs-body-sm\)\s*!important/);
    expect(stylesheet).toMatch(
      /@media \(max-width: 767px\)[\s\S]*min-height:\s*44px\s*!important/,
    );
  });

  it("does not apply text-action sizing to square or circular controls", () => {
    expect(stylesheet).toContain(":not(.tt-btn-square):not(.tt-btn-circle)");
    expect(stylesheet).toContain(".tt-btn-touch");
  });

  it("does not collapse conversation data rows to the action-button height", () => {
    expect(stylesheet).toMatch(
      /\.tt-btn:not\(\.conversation\)[\s\S]*--tt-size:\s*2rem/,
    );
    expect(stylesheet).toContain(
      ".tailkit-workspace-content button:not(.conversation)",
    );
  });
});
