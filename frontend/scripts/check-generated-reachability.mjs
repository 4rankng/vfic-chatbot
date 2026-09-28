#!/usr/bin/env node
/**
 * Report which generated Untitled UI files no application import can reach.
 *
 * WHY THIS EXISTS: `npx untitledui add <component>` writes a component *and its
 * siblings* — the `badges` run brought badges, and the `input` run brought a
 * dozen input variants, the tags set and 57 payment icons. Tailwind CSS v4 scans
 * files, not import graphs, so every one of those files compiles its utility
 * classes into the shipped stylesheet whether or not anything renders it. On
 * 2026-09-28 that dead weight measured 23.9 kB on the index sheet.
 *
 * WHAT IT DOES: resolves the static import graph from application code (anything
 * under `src/` that is NOT itself generated) into the three generated roots, and
 * prints the generated files outside that closure. Delete those files; re-install
 * any of them with `npx untitledui add <component> --yes`.
 *
 * SAFETY: it only reports. A file is "unreachable" here only when no app module
 * imports it, directly or transitively — but a component can still be reachable
 * through a path this script does not resolve (a dynamic `import()` in a string,
 * a package.json `exports` map, a test-only import). Prefer keeping a file you are
 * unsure about; the cost is CSS bytes, not correctness.
 *
 * Usage:
 *   node scripts/check-generated-reachability.mjs            # report
 *   node scripts/check-generated-reachability.mjs --keep a,b # report against a keep-set
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
process.chdir(frontendRoot);

/** Generated, dependency-owned roots. Everything here is CLI output. */
const GENERATED_ROOTS = [
  "src/components/base",
  "src/components/foundations",
  "src/utils",
];

const isGenerated = (file) =>
  GENERATED_ROOTS.some((root) => file.startsWith(`${root}/`));

const walk = (dir, visit) => {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(file, visit);
    else if (/\.(ts|tsx)$/.test(entry.name)) visit(file);
  }
};

const resolveSpecifier = (from, specifier) => {
  let base;
  if (specifier.startsWith("@/")) base = path.join("src", specifier.slice(2));
  else if (specifier.startsWith("."))
    // `path.join`, not `path.resolve`: resolve() would anchor a relative
    // specifier to process.cwd() and return an absolute path, which then fails
    // the string-prefix test in `isGenerated` and makes a live dependency look
    // unreachable.
    base = path.join(path.dirname(from), specifier);
  else return null;

  for (const suffix of [".ts", ".tsx", "/index.ts", "/index.tsx", ""]) {
    const candidate = base + suffix;
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
      return candidate;
    }
  }
  return null;
};

const readStaticImports = (file) =>
  [
    ...fs
      .readFileSync(file, "utf8")
      .matchAll(/(?:^|\n)\s*import[^;]*?from\s+["']([^"']+)["']/g),
  ].map((match) => match[1]);

const generated = [];
GENERATED_ROOTS.forEach((root) => walk(root, (file) => generated.push(file)));

const appFiles = [];
walk("src", (file) => {
  if (!isGenerated(file)) appFiles.push(file);
});

/** Files to treat as referenced even when no app import reaches them yet. */
const keepArguments = process.argv
  .find((argument) => argument.startsWith("--keep"))
  ?.split("=")[1];

// Entry points: generated files that application code imports directly, plus any
// explicitly kept file — the keep-set must seed the traversal, not be appended to
// its result, or a kept component's own dependencies are reported as dead.
const entries = new Set(
  (keepArguments ?? "")
    .split(",")
    .map((file) => file.trim())
    .filter((file) => file !== "" && fs.existsSync(file)),
);
for (const file of appFiles) {
  for (const specifier of readStaticImports(file)) {
    const resolved = resolveSpecifier(file, specifier);
    if (resolved && isGenerated(resolved)) entries.add(resolved);
  }
}

const reachable = new Set(entries);
const queue = [...entries];
while (queue.length > 0) {
  const file = queue.pop();
  for (const specifier of readStaticImports(file)) {
    const resolved = resolveSpecifier(file, specifier);
    if (resolved && isGenerated(resolved) && !reachable.has(resolved)) {
      reachable.add(resolved);
      queue.push(resolved);
    }
  }
}

const unreachable = generated.filter((file) => !reachable.has(file)).sort();

console.log(`generated files: ${generated.length}`);
console.log(`reachable:       ${reachable.size}`);
console.log(`unreachable:     ${unreachable.length}`);
if (entries.size > 0) {
  console.log("\nentry points (imported by app code):");
  for (const file of [...entries].sort()) console.log(`  ${file}`);
}
if (unreachable.length > 0) {
  const byDirectory = new Map();
  for (const file of unreachable) {
    const key = file.split("/").slice(0, 4).join("/");
    byDirectory.set(key, (byDirectory.get(key) ?? 0) + 1);
  }
  console.log("\nunreachable, grouped:");
  for (const [directory, count] of [...byDirectory].sort(
    (a, b) => b[1] - a[1],
  )) {
    console.log(`  ${String(count).padStart(4)}  ${directory}`);
  }
  console.log("\nunreachable files:");
  for (const file of unreachable) console.log(`  ${file}`);
}
