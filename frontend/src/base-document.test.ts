import { describe, expect, it } from "vitest";

const documents = import.meta.glob<string>("../index.html", {
  eager: true,
  import: "default",
  query: "?raw",
});

/**
 * The document shell is the one stylesheet that cannot be layered by Tailwind:
 * its inline `<style>` is unlayered, so any `body` declaration there outranks
 * every `@layer base` rule the app ships — including the one that puts the
 * product font (Be Vietnam Pro, chosen for Vietnamese coverage) on `body`.
 *
 * That is exactly how the console shipped: a template-leftover
 * `body { font-family: sans-serif }` painted every screen that does not set its
 * own family (users, bot runs, performance) in the system sans while the
 * workspaces rendered Be Vietnam Pro. The splash loader's own CSS is fine — its
 * text is `text-indent`-hidden — but the loaded app must own `font-family`.
 */
describe("index.html base document", () => {
  it("does not override the app's body font from the unlayered shell style", () => {
    const sources = Object.values(documents);
    expect(
      sources.length,
      "import.meta.glob matched no index.html",
    ).toBeGreaterThan(0);

    for (const source of sources) {
      expect(source).not.toMatch(/body\s*\{[^}]*font-family/);
    }
  });
});
