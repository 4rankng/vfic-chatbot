import { describe, expect, it } from "vitest";

import stylesheet from "./projects.css?raw";

describe("project list visual hierarchy", () => {
  it("keeps the project ledger on one continuous workspace surface", () => {
    expect(stylesheet).toMatch(
      /\.project-rollup-strip\s*\{[^}]*border-block:\s*1px solid var\(--border\)[^}]*border-radius:\s*0[^}]*background:\s*transparent/,
    );
    expect(stylesheet).toMatch(
      /\.project-rollup-strip span\s*\{[^}]*border-radius:\s*0[^}]*background:\s*transparent/,
    );
    expect(stylesheet).toMatch(
      /@media \(min-width: 768px\)[\s\S]*?\.inbox-bg-container\.project-workspace\s*\{[^}]*padding:\s*0/,
    );
    expect(stylesheet).toMatch(
      /@media \(min-width: 768px\)[\s\S]*?\.inbox-bg-container\.project-workspace \.project-app\s*\{[^}]*border-radius:\s*0[^}]*background:\s*transparent[^}]*box-shadow:\s*none/,
    );
    expect(stylesheet).toMatch(
      /@media \(min-width: 768px\)[\s\S]*?\.inbox-bg-container\.project-workspace \.project-center-panel\s*\{[^}]*background:\s*transparent/,
    );
  });

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
    // [^}]* (not [\s\S]*) pins each property to its owning rule block: the match
    // can't cross a closing brace, so it can't jump to an unrelated rule and pass
    // when the intended rule's property is missing.
    expect(stylesheet).toMatch(
      /\.project-accordion-content\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 767px\)[\s\S]*?\.project-category-mobile-select\s*\{[^}]*display:\s*block[^}]*min-height:\s*44px/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 767px\)[\s\S]*?\.project-category-grid\s*\{[^}]*display:\s*none/,
    );
    expect(stylesheet).toMatch(
      /\.project-category-editor-actions\s*>\s*:last-child\s*\{[^}]*grid-column:\s*1 \/ -1/,
    );
    expect(stylesheet).toMatch(
      /\.project-category-textarea\s*\{[^}]*field-sizing:\s*fixed[^}]*height:\s*min\(52dvh, 420px\)/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 359px\)[\s\S]*?\.project-category-editor-actions\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
  });

  it("keeps the selected category content beside the category list on desktop", () => {
    expect(stylesheet).toMatch(
      /\.project-category-workspace\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:\s*minmax\(220px, 280px\) minmax\(0, 1fr\)/,
    );
    expect(stylesheet).toMatch(
      /\.project-category-navigation\s*\{[^}]*border-right:\s*1px solid var\(--border\)/,
    );
    expect(stylesheet).toMatch(
      /\.project-category-workspace \.project-category-editor\s*\{[^}]*border-top:\s*0/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 767px\)[\s\S]*?\.project-category-workspace\s*\{[^}]*display:\s*block/,
    );
  });
});
