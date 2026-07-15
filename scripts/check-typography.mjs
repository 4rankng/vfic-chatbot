#!/usr/bin/env node
/**
 * check-typography.mjs — Typography drift guard.
 *
 * Scans the frontend for hard-coded font-size values that bypass the centralized
 * token scale (see docs/typography-system.md). Exits non-zero on violations so
 * it can gate CI / pre-commit.
 *
 * Allowed:
 *   - Token utilities: text-page-title, text-body, text-caption, etc.
 *   - Color arbitrary values: text-[var(--kb-teal)], text-[var(--success)]
 *   - font-size: var(--fs-*) or var(--crm-fs-*) in CSS (token consumers)
 *   - Letter-spacing arbitrary: tracking-[0.08em] (not a font size)
 *
 * Flagged:
 *   - Raw Tailwind font-size utilities: text-sm, text-xs, text-base, text-lg,
 *     text-xl, text-2xl, text-3xl (swept out 2026-07-15 — use a token instead)
 *   - Arbitrary font-size utilities: text-[11px], text-[1.25rem], text-[clamp(...)]
 *   - Raw px/rem font-size in component CSS (outside the allowlist files)
 *
 * Usage: node scripts/check-typography.mjs
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const FRONTEND = join(ROOT, "frontend", "src");

// Files allowed to DEFINE raw font-size values (token owners + branding).
// Component CSS that merely CONSUMES tokens (var(--fs-*)) is allowed anywhere.
const CSS_ALLOWLIST = new Set([
  "frontend/src/index.css",
  "frontend/src/components/atomic-crm/conversations/inbox/tokens.css",
]);

// Branding exceptions — surfaces with a documented reason to hold a fixed
// font-size that doesn't map cleanly to the scale (e.g. rubber-stamp motif).
// Keep this list small; every entry needs a line in docs/typography-system.md.
const BRANDING_ALLOWLIST = new Set([
  // Knowledge-center rubber-stamp motif (Fraunces, 10.5px uppercase).
  "frontend/src/index.css", // .kb-stamp lives here
]);

// Legacy surfaces under incremental migration. These files predate the token
// scale and still hold raw px/rem font-sizes. They are allowed for now so the
// check acts as a RATCHET — it blocks NEW hard-coded sizes while the legacy
// files migrate incrementally. Each entry must have a removal plan.
// See docs/typography-system.md → "Deferred work".
const LEGACY_ALLOWLIST = [
  // Chat surface: the inbox sub-CSS system uses the legacy --crm-fs-* / --chat-*
  // px-based tokens. Internally consistent; highest-traffic UI — migrate last.
  /^frontend\/src\/components\/atomic-crm\/conversations\/inbox\//,
  // Dashboard & performance page CSS: hero/outlier values were tokenized in the
  // 2026-07-12 migration; remaining values are small in-spec sizes pending sweep.
  "frontend/src/components/atomic-crm/dashboard/dashboard.css",
  "frontend/src/components/atomic-crm/performance/performance.css",
];

function isLegacy(rel) {
  return LEGACY_ALLOWLIST.some((entry) =>
    entry instanceof RegExp ? entry.test(rel) : entry === rel,
  );
}

function walk(dir, acc = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const rel = relative(ROOT, full).split(sep).join("/");
    if (statSync(full).isDirectory()) {
      walk(full, acc);
    } else if (
      rel.endsWith(".tsx") ||
      rel.endsWith(".ts") ||
      rel.endsWith(".css")
    ) {
      acc.push(rel);
    }
  }
  return acc;
}

const files = walk(FRONTEND);
const violations = [];

// Pattern: arbitrary font-size Tailwind utility, e.g. text-[11px], text-[1.25rem],
// text-[clamp(...)]. Matches a number (with optional unit) inside the brackets.
// Does NOT match text-[var(--...)] (color refs) — those start with "var".
const ARBITRARY_FS = /text-\[(?!var\()[\d.]+(?:px|rem|em|pt)\]/;
const ARBITRARY_FS_CLAMP = /text-\[clamp\(/;

// Raw Tailwind font-size utility classes (the built-in scale). These were swept
// out of the codebase on 2026-07-15 in favor of semantic tokens (text-page-title,
// text-body, text-helper, ...). Matches bare OR variant-prefixed forms
// (text-sm, md:text-lg, hover:text-xs, group-hover:text-base). Word-boundary on
// both sides so it never matches text-small / text-slate-500 / text-xxl-foo.
const RAW_SIZE_UTILITIES = ["sm", "xs", "base", "lg", "xl", "2xl", "3xl", "4xl", "5xl", "6xl", "7xl", "8xl", "9xl"];
const RAW_FS_CLASS = new RegExp(
  // optional variant prefix (e.g. "md:", "hover:", "group-hover:", "max-sm:")
  "(?:\\b[a-z0-9-]+:)*" +
  // the utility, not preceded by "-" (to skip text-9 → text-\[9\]) and at a class boundary
  `text-(?:${RAW_SIZE_UTILITIES.join("|")})\\b`,
);

for (const rel of files) {
  const full = join(ROOT, rel);
  let content;
  try {
    content = readFileSync(full, "utf8");
  } catch {
    continue;
  }
  const lines = content.split("\n");

  lines.forEach((line, i) => {
    const lineno = i + 1;

    // Raw Tailwind font-size utility classes (text-sm, text-lg, md:text-xl, ...).
    // Skip the token-owner CSS (index.css owns the @theme text-* definitions and
    // may reference the raw names in comments/aliases) and legacy CSS surfaces.
    if (
      !CSS_ALLOWLIST.has(rel) &&
      !isLegacy(rel) &&
      RAW_FS_CLASS.test(line)
    ) {
      const match = line.match(RAW_FS_CLASS);
      violations.push({
        file: rel,
        line: lineno,
        kind: "raw-tailwind-font-size-utility",
        detail: match[0],
        source: line.trim(),
      });
    }

    // Tailwind arbitrary font-size utilities (JSX + CSS).
    if (ARBITRARY_FS.test(line) || ARBITRARY_FS_CLAMP.test(line)) {
      const match =
        line.match(ARBITRARY_FS) || line.match(ARBITRARY_FS_CLAMP);
      violations.push({
        file: rel,
        line: lineno,
        kind: "arbitrary-font-size-utility",
        detail: match[0],
        source: line.trim(),
      });
    }

    // Raw font-size: <value> in CSS — only flag if NOT a var() consumer and
    // the file is NOT an allowlisted token owner / branding file.
    if (rel.endsWith(".css")) {
      const fsMatch = line.match(/font-size:\s*([^;]+)/);
      if (fsMatch) {
        const value = fsMatch[1].trim();
        const consumesToken =
          value.startsWith("var(") || value.includes("var(--fs") || value.includes("var(--crm-fs") || value.includes("var(--chat-fs") || value.includes("var(--text-");
        if (!consumesToken) {
          const allowed =
            CSS_ALLOWLIST.has(rel) ||
            BRANDING_ALLOWLIST.has(rel) ||
            isLegacy(rel);
          if (!allowed) {
            violations.push({
              file: rel,
              line: lineno,
              kind: "raw-font-size-in-css",
              detail: `font-size: ${value}`,
              source: line.trim(),
            });
          }
        }
      }
    }
  });
}

// Report
if (violations.length === 0) {
  console.log(
    "✓ Typography check passed — no hard-coded font sizes found.\n" +
      "  See docs/typography-system.md for the scale.",
  );
  process.exit(0);
}

console.error(
  `✗ Typography check failed — ${violations.length} hard-coded font size(s) found.\n` +
    "  Use a token from the scale (docs/typography-system.md) instead.\n",
);
for (const v of violations) {
  console.error(
    `  ${v.file}:${v.line}  [${v.kind}]  ${v.detail}\n` +
      `    ${v.source}`,
  );
}
console.error(
  "\n  If this is a legitimate exception, add the file to the allowlist in\n" +
    "  scripts/check-typography.mjs AND document it in docs/typography-system.md.",
);
process.exit(1);
