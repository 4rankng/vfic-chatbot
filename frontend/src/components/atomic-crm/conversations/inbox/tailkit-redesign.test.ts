import { describe, expect, it } from "vitest";

import stylesheet from "./tailkit-redesign.css?raw";

describe("Tailkit conversation controls", () => {
  it("renders the reply-mode control as an icon without decorative surfaces", () => {
    expect(stylesheet).toMatch(
      /\.mode-menu-trigger-icon\s*\{[\s\S]*border:\s*0;[\s\S]*background:\s*transparent;/,
    );
    expect(stylesheet).toMatch(
      /\.mode-menu-trigger-icon \.icon\s*\{[\s\S]*width:\s*18px;[\s\S]*height:\s*18px;/,
    );
    expect(stylesheet).toMatch(
      /\.mode-menu-trigger--primary,[\s\S]*border-color:\s*transparent;[\s\S]*background:\s*transparent;/,
    );
  });

  it("renders channel selectors as full-size icons without button chrome", () => {
    expect(stylesheet).toMatch(
      /\.channel-adapter-option\s*\{[\s\S]*border-color:\s*transparent;[\s\S]*background:\s*transparent;[\s\S]*box-shadow:\s*none;/,
    );
    expect(stylesheet).toMatch(
      /\.channel-adapter-option img\s*\{[\s\S]*width:\s*36px;[\s\S]*height:\s*36px;/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 767px\)[\s\S]*\.channel-adapter-option img\s*\{[\s\S]*width:\s*44px;[\s\S]*height:\s*44px;/,
    );
    expect(stylesheet).toMatch(
      /@media \(max-width: 767px\)[\s\S]*\.mode-menu-trigger-icon \.icon\s*\{[\s\S]*width:\s*20px;[\s\S]*height:\s*20px;/,
    );
  });
});
