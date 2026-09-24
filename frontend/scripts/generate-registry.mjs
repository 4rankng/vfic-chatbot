#!/usr/bin/env node

import { globSync } from "glob";
import fs from "node:fs";
import path from "node:path";

const registryPath = "registry.json";
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

const newRegistryContent = {
  ...registryContent,
  items: registryContent.items.map((item) => {
    if (item.name === "atomic-crm") {
      return {
        ...item,
        files,
      };
    }

    return item;
  }),
};

fs.writeFileSync(
  registryPath,
  JSON.stringify(newRegistryContent, null, 2),
  "utf-8",
);
