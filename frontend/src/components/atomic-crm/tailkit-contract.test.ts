import { describe, expect, it } from "vitest";

import appEntry from "../../index.css?raw";
import tailkitTokens from "../../styles/tailkit-tokens.css?raw";

/**
 * Tailkit compatibility contract.
 *
 * The Tailkit MCP emits plain React JSX whose styling leans on a NUMERIC
 * `secondary` colour scale (`bg-secondary-50`, `border-secondary-200`,
 * `text-secondary-700`, `ring-secondary-300/25`, `placeholder-secondary-400`, …).
 * This app defines no numeric scale of its own, so a Tailkit component pasted
 * straight into a feature folder lands as unstyled markup that looks broken.
 *
 * `src/styles/tailkit-tokens.css` is the single file that closes that gap, which
 * makes it load-bearing and easy to break from a distance. The assertions below
 * assert on source text rather than rendered layout, matching the established
 * FE-19 pattern in `css-scoping.test.ts` — the CSS build output is not available
 * to this browser-mode project (vitest configures only `react()`, not
 * `@tailwindcss/vite`, so `@theme` is never expanded here).
 */

/** Strip comments so prose in the header cannot satisfy or trip an assertion. */
const withoutComments = (css: string): string =>
  css.replace(/\/\*[\s\S]*?\*\//g, "");

/** Every shade Tailkit's emitted markup references today, plus two reserved. */
const REQUIRED_SHADES = [
  50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950,
] as const;

describe("Tailkit token contract", () => {
  it("declares every secondary shade Tailkit markup can reference", () => {
    const css = withoutComments(tailkitTokens);
    const missing = REQUIRED_SHADES.filter(
      (shade) => !css.includes(`--color-secondary-${shade}:`),
    );

    expect(
      missing,
      "Tailkit markup would render unstyled; add the shade to " +
        "src/styles/tailkit-tokens.css",
    ).toEqual([]);
  });

  it("never overrides the flat shadcn --color-secondary semantic slot", () => {
    // `--color-secondary` (no numeric suffix) is a different utility from
    // `--color-secondary-50` in Tailwind v4, so defining the scale does not
    // clobber it. Declaring it here WOULD: index.css redefines the underlying
    // `--secondary` custom property five times (:root, .dark, the inbox scope,
    // .kb-scope, .dark .kb-scope), and a flat `--color-secondary` here would
    // send shadcn components app-wide looking for a variable that is not set.
    const css = withoutComments(tailkitTokens);

    expect(
      /^\s*--color-secondary\s*:/m.test(css),
      "src/styles/tailkit-tokens.css must not declare --color-secondary; it " +
        "owns only the numeric Tailkit ramp",
    ).toBe(false);
  });

  it("is imported exactly once from the app entry", () => {
    // A second @import would emit the @theme block twice; a missing one means
    // every Tailkit component silently loses its colours.
    const imports = appEntry.match(
      /@import\s+["'][^"']*styles\/tailkit-tokens\.css["']/g,
    );

    expect(imports ?? []).toHaveLength(1);
  });

  it("declares the scale as @theme so the utilities are actually emitted", () => {
    // `@theme inline` resolves its values into the generated utility rather than
    // a :root custom property. Either form emits the utilities, but `@theme`
    // keeps the tokens overridable at runtime, which is what lets the scale
    // track the console's :root --workspace-* roles.
    expect(withoutComments(tailkitTokens)).toMatch(/@theme\s*\{/);
    expect(withoutComments(tailkitTokens)).not.toMatch(/@theme\s+inline\s*\{/);
  });

  it("gives every Tailkit shade a literal fallback", () => {
    // A bare `var(--workspace-line)` with no fallback becomes an invalid
    // declaration at computed-value time, which drops the property silently
    // rather than erroring — the hardest kind of regression to notice.
    const css = withoutComments(tailkitTokens);
    const withoutFallback = REQUIRED_SHADES.filter(
      (shade) =>
        css.includes(`--color-secondary-${shade}:`) &&
        !new RegExp(
          `--color-secondary-${shade}:\\s*var\\(--workspace-[a-z-]+,`,
        ).test(css) &&
        // 300/400/600/700/950 are color-mix() over workspace roles rather than
        // a bare var(), so the fallback rule differs for those.
        ![300, 400, 600, 700, 950].includes(shade),
    );

    expect(withoutFallback, "shade lacks a literal fallback").toEqual([]);
  });
});
