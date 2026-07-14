import { describe, expect, it } from "vitest";

import stylesheet from "./performance.css?raw";

const rule = (selector: string) => {
  const match = stylesheet.match(new RegExp(`${selector}\\s*\\{([^}]*)\\}`));
  if (!match) throw new Error(`Missing CSS rule: ${selector}`);
  return match[1];
};

describe("performance trend chart layers", () => {
  it("renders the target line above the bars without blocking their hover details", () => {
    const targetLine = rule("\\.performance-target-line");
    const bar = rule("\\.performance-trend-bar");

    expect(targetLine).toMatch(/z-index:\s*3/);
    expect(bar).toMatch(/z-index:\s*2/);
    expect(targetLine).toMatch(/pointer-events:\s*none/);
  });
});
