#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

import { DEPENDENCY_OWNED_PATHS as dependencyOwnedPaths } from "./dependency-owned-paths.mjs";
import { readJson } from "./read-json.mjs";

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

const registry = readJson(path.join(frontendRoot, "registry.json"));
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

const moduleScriptPattern = /\.(?:ts|tsx|js|jsx|mjs)$/;
const cssImportPattern = /@import\s+(?:url\()?["']([^"']+)["']/g;
const cssFilePattern = /\.css$/;
const packageJson = readJson(path.join(frontendRoot, "package.json"));

const readModuleSpecifiers = (file, absolute) => {
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

  return specifiers;
};

const readCssSpecifiers = (absolute) =>
  [...fs.readFileSync(absolute, "utf8").matchAll(cssImportPattern)].map(
    (match) => match[1],
  );

const readImportSpecifiers = (file) => {
  const absolute = path.join(frontendRoot, file);
  if (!fs.existsSync(absolute)) return [];
  if (moduleScriptPattern.test(file)) {
    return readModuleSpecifiers(file, absolute);
  }
  if (cssFilePattern.test(file)) return readCssSpecifiers(absolute);
  return [];
};

for (const file of manifestPaths) {
  readImportSpecifiers(file).forEach((specifier) =>
    checkDependency(file, specifier),
  );
}

// The install list is the one part of the manifest a merge can silently
// re-break: the upstream manifest this fork forked from brought back packages
// package.json no longer carries, and every published consumer installs them.
// Nothing above inspects it, so the two sources generate-registry.mjs derives
// it from are re-checked here: every published import has to be declared, and
// every declared range has to still be the one package.json carries.
const toPackageName = (specifier) => {
  if (
    specifier === "" ||
    specifier.startsWith(".") ||
    specifier.startsWith("@/") ||
    specifier.startsWith("/") ||
    specifier.startsWith("node:") ||
    specifier.startsWith("#")
  ) {
    return null;
  }

  const segments = specifier.split("/");
  return specifier.startsWith("@")
    ? segments.slice(0, 2).join("/")
    : segments[0];
};

for (const item of registry.items) {
  const declared = new Map();

  for (const entry of item.dependencies ?? []) {
    const separator = entry.lastIndexOf("@");
    const name = separator > 0 ? entry.slice(0, separator) : entry;
    const range = separator > 0 ? entry.slice(separator + 1) : "";
    declared.set(name, range);
    const expected = packageJson.dependencies?.[name];
    if (!expected) {
      errors.push(
        `${item.name} declares ${entry}, which package.json does not list in dependencies`,
      );
    } else if (expected !== range) {
      errors.push(
        `${item.name} pins ${name}@${range} but package.json carries ${expected}`,
      );
    }
  }

  for (const file of (item.files ?? []).map((entry) => entry.path)) {
    for (const specifier of readImportSpecifiers(file)) {
      const name = toPackageName(specifier);
      if (name && !declared.has(name)) {
        errors.push(
          `${item.name} does not declare ${name}, imported by ${file}`,
        );
      }
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
