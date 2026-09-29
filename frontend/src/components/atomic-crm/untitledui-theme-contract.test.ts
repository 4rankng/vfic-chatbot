import { describe, expect, it } from "vitest";

import appEntry from "../../index.css?raw";
import untitledTokens from "../../styles/untitledui-theme.css?raw";

/**
 * Untitled UI token-layer contract.
 *
 * `npx untitledui add <component>` writes real Untitled UI v8 components into
 * `src/components/base/`, styled through Untitled UI's own theme vocabulary. This
 * app already owns a design system, and the two vocabularies collide on exactly
 * four utility names: Tailwind resolves `bg-primary` from
 * `--background-color-primary` the moment that key exists, so importing Untitled
 * UI's namespaces verbatim would silently repaint every existing `bg-primary`,
 * `bg-secondary`, `text-primary` and `border-primary` in the console.
 *
 * These assertions read source text rather than rendered layout, because this
 * browser-mode project runs only `react()` — `@tailwindcss/vite` is not
 * configured here, so `@theme` is never expanded in the test environment.
 */

/** Strip comments so prose in the header cannot satisfy an assertion. */
const withoutComments = (css: string): string =>
  css.replace(/\/\*[\s\S]*?\*\//g, "");

/** Keys of the first top-level block matching `header`, e.g. `@theme {`. */
const blockKeys = (css: string, header: RegExp, key: RegExp): string[] => {
  const block = header.exec(withoutComments(css))?.[1];
  if (block === undefined) return [];
  return [...block.matchAll(key)].map((match) => match[1]);
};

const tokenKeys = (css: string): string[] =>
  blockKeys(css, /@theme\s*\{([\s\S]*?)\n\}/, /^\s*(--[a-z0-9_*-]+)\s*:/gm);

const rootBindings = (css: string): Record<string, string> =>
  Object.fromEntries(
    [
      ...(
        /^:root\s*\{([\s\S]*?)\n\}/m.exec(withoutComments(css))?.[1] ?? ""
      ).matchAll(/^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);/gm),
    ].map((match) => [match[1], match[2].trim()]),
  );

/** The four names both systems define, and the console's own values for them. */
const CONSOLE_OWNED = {
  "--background-color-primary": "var(--primary)",
  "--background-color-secondary": "var(--secondary)",
  "--text-color-primary": "var(--primary)",
  "--border-color-primary": "var(--primary)",
} as const;

describe("Untitled UI token contract", () => {
  it("is imported exactly once from the app entry", () => {
    const imports = withoutComments(appEntry).match(
      /styles\/untitledui-theme\.css/g,
    );

    expect(
      imports,
      "src/index.css must import the layer exactly once",
    ).toHaveLength(1);
  });

  it("declares the namespaces Untitled UI components compile against", () => {
    const keys = new Set(tokenKeys(untitledTokens));
    const required = [
      // Utility namespaces: `bg-primary`, `text-secondary`, `border-primary`,
      // `ring-brand`, `outline-brand` in a generated component.
      "--background-color-primary",
      "--text-color-secondary",
      "--border-color-primary",
      "--ring-color-brand",
      "--outline-color-brand",
      // Alias families the components read directly.
      "--color-utility-neutral-50",
      "--color-utility-brand-700",
      "--color-fg-quaternary",
      "--color-text-primary",
      "--color-bg-primary",
      // Type + shadow scale additions with no Tailwind default.
      "--text-md",
      "--text-display-lg",
      "--shadow-xs-skeuomorphic",
    ];
    const missing = required.filter((key) => !keys.has(key));

    expect(
      missing,
      "a freshly installed Untitled UI component would render unstyled; add " +
        "the token to src/styles/untitledui-theme.css",
    ).toEqual([]);
  });

  it("keeps every console-owned name on the console's own variable", () => {
    const bindings = rootBindings(untitledTokens);

    for (const [key, value] of Object.entries(CONSOLE_OWNED)) {
      expect(
        bindings[key],
        `${key} must stay bound to ${value}: the console already uses the ` +
          "matching utility with its shadcn meaning",
      ).toBe(value);
    }
  });

  it("re-binds those four keys for Untitled UI subtrees only", () => {
    const scope = /^\.uu-scope\s*\{([\s\S]*?)\n\}/m.exec(
      withoutComments(untitledTokens),
    )?.[1];
    const source = withoutComments(untitledTokens);
    const scopeAt = source.indexOf(".uu-scope");
    const rootAt = source.indexOf(":root");

    for (const key of Object.keys(CONSOLE_OWNED)) {
      expect(
        scope,
        "Untitled UI subtrees need the library's own semantics",
      ).toContain(key);
    }
    // Same specificity, so the scope must come last to win on a subtree root.
    expect(scopeAt).toBeGreaterThan(rootAt);
  });

  it("never redeclares a flat console token, so no utility is captured twice", () => {
    const consoleKeys = new Set(
      blockKeys(
        appEntry,
        /@theme inline\s*\{([\s\S]*?)\n\}/,
        /^\s*--color-([a-z0-9-]+)\s*:/gm,
      ),
    );
    const declared = tokenKeys(untitledTokens)
      .filter((key) => key.startsWith("--color-"))
      .map((key) => key.slice("--color-".length));
    const clashes = declared.filter((name) => consoleKeys.has(name));

    expect(
      clashes,
      "these names are already a flat console token; declaring them again " +
        "would repaint existing console markup",
    ).toEqual([]);
  });

  it("leaves the console's type, radius, shadow and font scale alone", () => {
    const protectedKeys = [
      "--text-xs:",
      "--text-sm:",
      "--text-lg:",
      "--text-xl:",
      "--radius-",
      "--shadow-xs:",
      "--shadow-sm:",
      "--shadow-md:",
      "--shadow-lg:",
      "--shadow-xl:",
      "--shadow-2xl:",
      "--shadow-3xl:",
      "--font-display:",
      "--font-body:",
      "--font-mono:",
    ];
    const declared = withoutComments(untitledTokens);
    const clashed = protectedKeys.filter((key) => declared.includes(key));

    expect(
      clashed,
      "Untitled UI's values here match Tailwind's defaults or would reflow the " +
        "console; see the header of src/styles/untitledui-theme.css",
    ).toEqual([]);
  });
});
