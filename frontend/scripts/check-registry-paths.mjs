#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const registry = JSON.parse(
  fs.readFileSync(path.join(frontendRoot, "registry.json"), "utf8"),
);
const manifestFiles = registry.items.flatMap((item) => item.files ?? []);
const manifestPaths = new Set(manifestFiles.map(({ path: file }) => file));
const errors = [];

for (const file of manifestFiles) {
  if (!fs.existsSync(path.join(frontendRoot, file.path))) {
    errors.push(`missing manifest path: ${file.path}`);
  }
}

if (manifestPaths.size !== manifestFiles.length) {
  errors.push("registry contains duplicate file paths");
}

for (const file of manifestPaths) {
  if (/\.(?:test|spec)\.[^.]+$|\.stories\.[^.]+$/.test(file)) {
    errors.push(`test-only file is published: ${file}`);
  }
}

const dependencyOwnedPaths = [
  "src/components/admin/",
  "src/components/ui/",
  "src/hooks/use-mobile.ts",
  "src/lib/utils.ts",
];
const nonTextAssetExtensions = new Set([".png", ".webp"]);
const candidates = [
  "",
  ".ts",
  ".tsx",
  ".js",
  ".jsx",
  ".mjs",
  ".css",
  ".png",
  ".webp",
  ".svg",
  "/index.ts",
  "/index.tsx",
  "/index.js",
  "/index.jsx",
];

const resolveLocalImport = (from, specifier) => {
  let base;
  if (specifier.startsWith("@/")) {
    base = path.join("src", specifier.slice(2));
  } else if (specifier.startsWith(".")) {
    base = path.join(path.dirname(from), specifier);
  } else {
    return null;
  }

  for (const suffix of candidates) {
    const candidate = path.posix.normalize(`${base}${suffix}`);
    const absolute = path.join(frontendRoot, candidate);
    if (fs.existsSync(absolute) && fs.statSync(absolute).isFile()) {
      return candidate;
    }
  }
  return undefined;
};

const checkDependency = (from, specifier) => {
  const dependency = resolveLocalImport(from, specifier);
  if (dependency === null) return;
  if (dependency === undefined) {
    errors.push(`unresolved local import: ${from} -> ${specifier}`);
    return;
  }
  if (manifestPaths.has(dependency)) return;
  if (dependencyOwnedPaths.some((prefix) => dependency.startsWith(prefix))) {
    return;
  }
  // The shadcn registry format serializes file content as UTF-8 and cannot
  // publish binary imports. Their checked-in paths are still validated here.
  if (nonTextAssetExtensions.has(path.extname(dependency))) return;
  errors.push(`unpublished local dependency: ${from} -> ${dependency}`);
};

for (const file of manifestPaths) {
  const absolute = path.join(frontendRoot, file);
  if (!fs.existsSync(absolute)) continue;

  if (/\.(?:ts|tsx|js|jsx|mjs)$/.test(file)) {
    const source = ts.createSourceFile(
      file,
      fs.readFileSync(absolute, "utf8"),
      ts.ScriptTarget.Latest,
      true,
    );
    const specifiers = [];

    for (const statement of source.statements) {
      if (
        (ts.isImportDeclaration(statement) ||
          ts.isExportDeclaration(statement)) &&
        statement.moduleSpecifier &&
        ts.isStringLiteral(statement.moduleSpecifier)
      ) {
        specifiers.push(statement.moduleSpecifier.text);
      }
    }

    const visit = (node) => {
      if (
        ts.isCallExpression(node) &&
        node.expression.kind === ts.SyntaxKind.ImportKeyword &&
        node.arguments[0] &&
        ts.isStringLiteral(node.arguments[0])
      ) {
        specifiers.push(node.arguments[0].text);
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
    specifiers.forEach((specifier) => checkDependency(file, specifier));
  } else if (file.endsWith(".css")) {
    const css = fs.readFileSync(absolute, "utf8");
    for (const match of css.matchAll(/@import\s+(?:url\()?["']([^"']+)["']/g)) {
      checkDependency(file, match[1]);
    }
  }
}

if (errors.length > 0) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log(
  `Registry paths and local text dependencies are complete (${manifestPaths.size} files).`,
);
