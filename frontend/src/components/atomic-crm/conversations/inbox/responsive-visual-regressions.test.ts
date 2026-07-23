import { describe, expect, it } from "vitest";

import featureStyles from "./features.css?raw";
import personaResponsiveStyles from "./personas-responsive.css?raw";

describe("responsive workspace visual regressions", () => {
  it("keeps the knowledge title on the shared page-title scale", () => {
    expect(featureStyles).toMatch(
      /\.knowledge-command-header h1[\s\S]*font-size:\s*var\(--fs-page-title\)/,
    );
  });

  it("keeps knowledge disclosures compact and within the phone viewport", () => {
    expect(featureStyles).toMatch(
      /\.knowledge-unit-disclosure > summary[\s\S]*min-height:\s*68px/,
    );
    expect(featureStyles).toMatch(
      /\.knowledge-unit-disclosure\[open\] \.knowledge-unit-chevron[\s\S]*transform:\s*rotate\(180deg\)/,
    );
  });

  it("shows every settings destination in a tablet grid", () => {
    expect(featureStyles).toMatch(
      /@media \(min-width: 768px\) and \(max-width: 900px\)[\s\S]*\.settings-side-nav-list[\s\S]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/,
    );
  });

  it("stacks Agent scope and activity instead of squeezing both columns", () => {
    expect(personaResponsiveStyles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*\.persona-scope-activity-grid[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
  });
});
