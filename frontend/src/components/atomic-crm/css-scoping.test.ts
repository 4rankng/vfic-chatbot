import { describe, expect, it } from "vitest";

const sheets = import.meta.glob<string>("../../**/*.css", {
  eager: true,
  import: "default",
  query: "?raw",
});

/**
 * FE-19 — feature stylesheets are not scoped by module.
 *
 * `.inbox-bg-container` is one shared container class carried by six workspace
 * roots (inbox, profile, project, persona, settings, knowledge), so a selector
 * nesting under it as a *descendant* reaches every workspace at once. The
 * correct shape is the compound form projects.css already uses:
 * `.inbox-bg-container.project-workspace`.
 *
 * Folding the existing rules is deliberately incremental — each sheet gets
 * scoped the next time it is opened, because a big-bang rewrite needs visual QA
 * across all six screens (TEST-10: the CSS tests assert source text, not
 * rendered layout). This ratchet stops the debt growing meanwhile: the number
 * may go DOWN only. Lower it when you scope a sheet; never raise it.
 */
const MAX_UNSCOPED_RULES = 689;

const selectorsOf = (css: string): string[] => {
  const out: string[] = [];
  let depth = 0;
  let buffer = "";
  for (const ch of css) {
    if (ch === "{") {
      if (depth === 0) out.push(buffer);
      buffer = "";
      depth += 1;
    } else if (ch === "}") {
      depth -= 1;
      buffer = "";
    } else if (depth === 0) {
      buffer += ch;
    }
  }
  return out;
};

describe("feature CSS scoping ratchet (FE-19)", () => {
  it("does not add rules nested under the shared inbox-bg-container", () => {
    expect(Object.keys(sheets).length, "import.meta.glob matched no stylesheets").toBeGreaterThan(20);

    const byFile = Object.entries(sheets)
      .map(([file, css]) => {
        const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
        const count = selectorsOf(stripped)
          .flatMap((selector) => selector.split(","))
          .filter((selector) => /\.inbox-bg-container(?!\.)\s+[A-Za-z.[:#]/.test(selector)).length;
        return [file.replace(/^\.\.\/\.\.\//, "src/"), count] as const;
      })
      .filter(([, count]) => count > 0)
      .sort((a, b) => b[1] - a[1]);
    const total = byFile.reduce((sum, [, count]) => sum + count, 0);

    expect(
      total,
      `Unscoped selectors rose from ${MAX_UNSCOPED_RULES} to ${total}. Scope new rules under the ` +
        "feature's own container class (.inbox-bg-container.<workspace>) instead of raising this cap.\n" +
        byFile
          .slice(0, 8)
          .map(([file, count]) => `  ${count}  ${file}`)
          .join("\n"),
    ).toBeLessThanOrEqual(MAX_UNSCOPED_RULES);
  });

  it("keeps the compound scoping pattern in use", () => {
    const compound = Object.values(sheets).filter((css) =>
      /\.inbox-bg-container\.[A-Za-z0-9_-]+/.test(css),
    ).length;

    expect(compound, "no sheet uses the compound .inbox-bg-container.<workspace> form").toBeGreaterThan(0);
  });
});
