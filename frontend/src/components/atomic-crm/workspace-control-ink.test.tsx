import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it } from "vitest";

import "@/index.css";
import "@/components/atomic-crm/conversations/inbox/base.css";

// Guards the workspace button reset in `conversations/inbox/base.css`.
//
// That reset shipped UNLAYERED, and an unlayered rule outranks every Tailwind
// utility (they all live in `@layer utilities`). So `.inbox-bg-container button
// { color: inherit }` beat each button's own `text-*`: the projects workspace
// painted `--primary` ink on the `--primary` action fill (3.4:1) and the
// bot-run suppressed label (white on cream) disappeared entirely. It is in
// `@layer base` now, so a declared utility wins while a plain button still
// inherits the workspace ink.
//
// The probe declares its utility at run time instead of using a class from the
// app: this browser project does not emit the full daisyUI/`@theme` scale, so a
// named utility could resolve to nothing and pass for the wrong reason.

afterEach(async () => {
  await cleanup();
});

type LayerRule = { selector: string; color: string };

const layerRules = (layerName: string): LayerRule[] => {
  const found: LayerRule[] = [];
  const visit = (rules: CSSRuleList) => {
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSLayerBlockRule) {
        if (rule.name !== layerName) continue;
        const collect = (inner: CSSRuleList) => {
          for (const nested of Array.from(inner)) {
            if (nested instanceof CSSStyleRule) {
              found.push({
                selector: nested.selectorText,
                color: nested.style.getPropertyValue("color"),
              });
            } else if (nested instanceof CSSLayerBlockRule) {
              collect(nested.cssRules);
            }
          }
        };
        collect(rule.cssRules);
        continue;
      }
      // `@media` / `@supports` wrappers keep their inner rules reachable.
      if (rule instanceof CSSMediaRule || rule instanceof CSSSupportsRule) {
        visit(rule.cssRules);
      }
    }
  };

  for (const sheet of Array.from(document.styleSheets)) {
    try {
      visit(sheet.cssRules);
    } catch {
      // Cross-origin sheets (none in this app) cannot be introspected.
    }
  }
  return found;
};

describe("workspace control ink", () => {
  it("lets a declared utility outrank the workspace inherit reset", async () => {
    const probe = document.createElement("style");
    probe.textContent =
      "@layer utilities { .probe-ink { color: rgb(1, 2, 3); } }";
    document.head.appendChild(probe);

    try {
      const screen = await render(
        <div className="inbox-bg-container">
          <button type="button" className="probe-ink">
            Nhãn nút
          </button>
        </div>,
      );

      const button = screen.getByRole("button", { name: "Nhãn nút" });
      expect(getComputedStyle(button.element()).color).toBe("rgb(1, 2, 3)");
    } finally {
      probe.remove();
    }
  });

  it("keeps the workspace button reset inside the base layer", () => {
    const reset = layerRules("base").filter(
      (rule) =>
        rule.selector === ".inbox-bg-container button" &&
        rule.color === "inherit",
    );

    expect(reset.length).toBeGreaterThan(0);
    expect(layerRules("utilities").map((rule) => rule.selector)).not.toContain(
      ".inbox-bg-container button",
    );
  });
});
