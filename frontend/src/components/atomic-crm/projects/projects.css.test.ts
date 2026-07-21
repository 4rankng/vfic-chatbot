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

  it("keeps the desktop knowledge hierarchy inside narrow accordion tracks", () => {
    expect(stylesheet).toMatch(
      /\.project-accordion-content[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 767px\)[\s\S]*\.project-category-grid[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/,
    );
    expect(stylesheet).toMatch(
      /\.project-category-editor-actions > :last-child[\s\S]*grid-column:\s*1 \/ -1/,
    );
    expect(stylesheet).toMatch(
      /\.project-category-textarea[\s\S]*field-sizing:\s*fixed[\s\S]*height:\s*min\(52dvh, 420px\)/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 359px\)[\s\S]*\.project-category-editor-actions[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
  });
});
