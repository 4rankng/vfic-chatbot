#!/usr/bin/env node

import { globSync } from "glob";
import ts from "typescript";
import fs from "node:fs";
import path from "node:path";

const registryPath = "registry.json";
const packageJsonPath = "package.json";
const basePath = "src";
const atomicCrmComponentsPath = path.join(basePath, "components", "atomic-crm");
const supabaseComponentsPath = path.join(basePath, "components", "supabase");
const hooksPath = path.join(basePath, "hooks");
const libPath = path.join(basePath, "lib");

const excludedHooks = [
  "filter-context.tsx",
  "saved-queries.tsx",
  "use-mobile.ts",
  "useSupportCreateSuggestion.tsx",
];

const excludedLibFiles = [
  "field.type.ts",
  "genericMemo.ts",
  "i18nProvider.ts",
  "sanitizeInputRestProps.ts",
  "utils.ts",
];

// Vite's boilerplate logo. Nothing imports it, so publishing it would ship dead
// bytes into every install of the registry.
const excludedAssetFiles = ["react.svg"];

const testFilePattern = "**/*.{test,spec}.*";
const storyFilePattern = "**/*.stories.*";
const stylePattern = "**/*.css";
const assetPattern = "**/*.svg";

// Test-only wrappers. The patterns above cannot see them because they are not
// named like tests, and a published file that only test files import is dead
// weight for every consumer of the registry.
const excludedTestHelpers = ["**/TestMessages.tsx"];

// Test-only sources must never reach the manifest: check-registry-paths.mjs
// rejects them outright, and only the component globs excluded them before.
const ignoreTests = {
  ignore: [testFilePattern, storyFilePattern, ...excludedTestHelpers],
};

const atomicCrmComponents = globSync(
  path.join(atomicCrmComponentsPath, "**", "*.ts*"),
  ignoreTests,
);
const supabaseComponents = globSync(
  path.join(supabaseComponentsPath, "**", "*.ts*"),
  ignoreTests,
);
const hooks = globSync(path.join(hooksPath, "**", "*.ts*"), ignoreTests).filter(
  (hook) => {
    return !excludedHooks.includes(path.basename(hook));
  },
);
const libFiles = globSync(path.join(libPath, "**", "*.ts*"), ignoreTests).filter(
  (file) => {
    return !excludedLibFiles.includes(path.basename(file));
  },
);

// Feature stylesheets ship with their feature. Every glob above is a component
// glob, so the app entry `src/index.css` and its non-feature siblings
// (`src/flat-surfaces.css`, `src/styles/untitledui.css`) stay out by
// construction rather than by an ever-growing exclusion list.
const styles = [
  ...globSync(path.join(atomicCrmComponentsPath, "**", stylePattern)),
  ...globSync(path.join(supabaseComponentsPath, "**", stylePattern)),
];
const assets = globSync(path.join(basePath, "assets", "**", assetPattern)).filter(
  (file) => !excludedAssetFiles.includes(path.basename(file)),
);

const registryContent = JSON.parse(fs.readFileSync(registryPath, "utf-8"));

const files = [
  ...atomicCrmComponents.map((path) => {
    return {
      path,
      type: "registry:component",
    };
  }),
  ...supabaseComponents.map((path) => {
    return {
      path,
      type: "registry:component",
    };
  }),
  ...hooks.map((path) => {
    return {
      path,
      type: "registry:hook",
    };
  }),
  ...libFiles.map((path) => {
    return {
      path,
      type: "registry:lib",
    };
  }),
  ...styles.map((path) => {
    return {
      path,
      type: "registry:style",
    };
  }),
  ...assets.map((path) => {
    return {
      path,
      type: "registry:file",
      target: `~/${path}`,
    };
  }),
];

// The published install list has to be derived, never hand-maintained: the
// upstream manifest shipped packages this fork dropped from package.json, and
// every consumer of the block paid for them. Deriving it from the files this
// script actually publishes (and pinning each name to the range package.json
// carries) means a dropped dependency disappears from the block the next time
// the manifest is generated, and a new import cannot ship unlisted.
const moduleScriptPattern = /\.(?:ts|tsx|js|jsx|mjs)$/;
const cssImportPattern = /@import\s+(?:url\()?["']([^"']+)["']/g;
// Stylesheets are read for their `@import` too: a published style that pulls
// a package entry needs it in the install list as much as a component does.
// Binary assets carry no imports and are the only published type skipped.
const packageImportFileTypes = new Set([
  "registry:component",
  "registry:hook",
  "registry:lib",
  "registry:style",
]);

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

const readModuleSpecifiers = (file) => {
  const source = ts.createSourceFile(
    file,
    fs.readFileSync(file, "utf-8"),
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

const deriveDependencies = (files) => {
  const importedBy = new Map();

  for (const file of files) {
    if (!packageImportFileTypes.has(file.type)) continue;

    const specifiers = moduleScriptPattern.test(file.path)
      ? readModuleSpecifiers(file.path)
      : [...fs.readFileSync(file.path, "utf-8").matchAll(cssImportPattern)].map(
          (match) => match[1],
        );

    for (const specifier of specifiers) {
      const name = toPackageName(specifier);
      if (name && !importedBy.has(name)) {
        importedBy.set(name, file.path);
      }
    }
  }

  const { dependencies } = JSON.parse(
    fs.readFileSync(packageJsonPath, "utf-8"),
  );

  return [...importedBy.keys()].sort().map((name) => {
    const range = dependencies?.[name];
    if (!range) {
      throw new Error(
        `${importedBy.get(name)} imports "${name}", which ${packageJsonPath} does not list in dependencies`,
      );
    }
    return `${name}@${range}`;
  });
};

const dependencies = deriveDependencies(files);

const newRegistryContent = {
  ...registryContent,
  items: registryContent.items.map((item) => {
    if (item.name === "atomic-crm") {
      return {
        ...item,
        dependencies,
        files,
      };
    }

    return item;
  }),
};

fs.writeFileSync(
  registryPath,
  `${JSON.stringify(newRegistryContent, null, 2)}\n`,
  "utf-8",
);
