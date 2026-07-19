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

  it("keeps header actions subordinate to the page title", () => {
    const title = rule("\\.performance-header h1");
    const window = rule("\\.performance-window");
    const segment = rule("\\.performance-window button");
    const refresh = rule("\\.performance-refresh");

    expect(title).toMatch(/font-weight:\s*var\(--fw-bold\)/);
    expect(window).toMatch(/padding:\s*0\.125rem/);
    expect(segment).toMatch(/min-height:\s*1\.625rem/);
    expect(segment).toMatch(/font-size:\s*var\(--fs-body-sm\)/);
    expect(segment).toMatch(/font-weight:\s*var\(--fw-semibold\)/);
    expect(refresh).toMatch(/min-height:\s*2rem/);
  });

  it("uses the page title as the top of the mobile type and spacing scale", () => {
    const mobile = stylesheet.slice(stylesheet.indexOf("@media (max-width: 720px)"));

    expect(mobile).toMatch(
      /\.performance-header h1\s*\{[^}]*font-size:\s*var\(--fs-page-title\)[^}]*line-height:\s*28px/s,
    );
    expect(mobile).toMatch(
      /\.performance-header > div > p:last-child\s*\{[^}]*font-size:\s*var\(--fs-body-sm\)[^}]*line-height:\s*18px/s,
    );
    expect(mobile).toMatch(
      /\.performance-window button\s*\{[^}]*min-height:\s*36px[^}]*font-size:\s*var\(--fs-body-sm\)/s,
    );
    expect(mobile).toMatch(
      /\.performance-metric\s*\{[^}]*border-radius:\s*12px[^}]*padding:\s*10px/s,
    );
    expect(mobile).toMatch(
      /\.performance-metric strong\s*\{[^}]*font-size:\s*22px[^}]*line-height:\s*26px/s,
    );
    expect(mobile).toMatch(
      /\.performance-trend\s*\{[^}]*height:\s*152px/s,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 420px\)[\s\S]*\.performance-refresh-prefix\s*\{[^}]*display:\s*none/s,
    );
  });
});
