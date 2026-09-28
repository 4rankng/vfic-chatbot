import { render } from "vitest-browser-react";
import { describe, expect, it } from "vitest";

import { User01, UserCheck01 } from "@untitledui/icons";

/**
 * Design-system dependency smoke test.
 *
 * Phase 2 added `@untitledui/icons` so the Untitled UI MCP's `search_icons` tool
 * yields icons an agent can actually import. That value is only real if the
 * package resolves, its PascalCase export names match what the MCP reports, and
 * the components render under this app's React 19 runtime.
 *
 * Without this, a missing or renamed export would not surface until an agent
 * pasted an icon into a screen mid-task, where the failure would look like a
 * broken build rather than a design-tooling problem.
 *
 * The names below came from `mcp__untitledui__search_icons(category: "users")`.
 * If the package is upgraded and an export disappears, this fails first.
 */
describe("Untitled UI icon dependency", () => {
  it("exports icons under the exact names the MCP reports", () => {
    expect(typeof User01).toBe("function");
    expect(typeof UserCheck01).toBe("function");
  });

  it("renders an icon as an accessible SVG", async () => {
    const screen = await render(<User01 aria-label="Ứng viên" />);
    const icon = screen.container.querySelector("svg");

    expect(icon).not.toBeNull();
    // Untitled UI icons are Heroicons-derived, so they carry a viewBox.
    expect(icon?.getAttribute("viewBox")).toBeTruthy();
    expect(icon?.getAttribute("aria-label")).toBe("Ứng viên");
  });
});
