import { describe, expect, it } from "vitest";

import stylesheet from "./projects.css?raw";

describe("project list visual hierarchy", () => {
  it("keeps the mobile create action subordinate to the page title", () => {
    expect(stylesheet).toMatch(
      /\.project-command-header h1[\s\S]*font-size:\s*var\(--fs-page-title\)/,
    );
    expect(stylesheet).toMatch(
      /\.project-command-actions \[data-slot="button"\][\s\S]*font-size:\s*var\(--fs-body-sm\)/,
    );
    expect(stylesheet).toMatch(
      /\.project-command-actions \[data-slot="button"\]::after[\s\S]*inset:\s*-6px/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 479px\)[\s\S]*\.project-create-button[\s\S]*width:\s*32px/,
    );
  });

  it("uses a compact mobile project summary", () => {
    expect(stylesheet).toMatch(
      /\.project-accordion-trigger[\s\S]*padding:\s*11px 12px/,
    );
    expect(stylesheet).toMatch(
      /\.project-accordion-facts > div[\s\S]*padding:\s*6px 8px/,
    );
    expect(stylesheet).toContain("-webkit-line-clamp: 2");
  });
});
