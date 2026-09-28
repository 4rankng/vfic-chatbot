#!/usr/bin/env node
/**
 * check-doc-links.mjs — routing integrity guard.
 *
 * The agent constitution routes every agent to a set of documents, paths, and
 * `make` targets. When one of those targets is deleted or moved, the routing
 * file keeps pointing at it: `65069078` deleted `AGENTS.md` and all of
 * `standards/` while the routing file still sent agents there, and the
 * 2026-09-27 sweep had to reconstruct the completion checklist from an old
 * report because the checklist itself was gone. This gate makes that failure
 * loud instead of silent. It is the same class of check as the Alembic
 * docs-drift step in the root `Makefile` release gate.
 *
 * Checked, for every scanned document:
 *   1. every repo-relative path in an inline code span or a markdown link
 *      target resolves to a real file or directory;
 *   2. every `make <target>` / `make -C <dir> <target>` in an inline code span
 *      or a fenced bash block names a target that the referenced Makefile
 *      actually declares.
 *
 * `.claude/` is not scanned and must not be: it is machine-local (see
 * `.gitignore`), so a fresh clone has none of it and any path routed into it
 * would fail this gate for everyone but the machine that installed it.
 *
 * Usage: node scripts/check-doc-links.mjs
 * Exits 1 with a `Release blocked:` line when any target is missing.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** Documents whose routing is load-bearing, in the order they are reported. */
const SCANNED_DOCUMENTS = [
  "AGENTS.md",
  "standards/agent-completion-checklist.md",
  "standards/definition-of-done.md",
  "standards/review-checklist.md",
];

/**
 * First path segment of anything that is genuinely a repository location.
 * A token whose first segment is not listed here is prose, a symbol, or a
 * command, and is not this gate's business.
 */
const REPO_ROOTS = new Set([
  "backend",
  "frontend",
  "docs",
  "standards",
  "plans",
  "kanban",
  "scripts",
  ".claude",
  ".agentkit",
  ".github",
  ".vscode",
]);

/** Root-level basenames that are real repository locations. */
const REPO_ROOT_FILES = new Set([
  "AGENTS.md",
  "CLAUDE.md",
  "Makefile",
  "README.md",
  "package.json",
  "pyproject.toml",
  "uv.lock",
  "docker-compose.yml",
  "Caddyfile",
  ".gitignore",
  ".mcp.json",
  ".env.example",
]);

/** Characters that mean a token is a template, a glob, or a shell fragment. */
const NON_PATH = /[\s*?<>{}\[\]|\\$`()"'=+;!~^&#@:,]/;

const GENERATED_BLOCK_START = "<!-- REPOWISE:START";

const readDocument = (relativePath) => {
  const absolute = join(ROOT, relativePath);
  if (!existsSync(absolute)) return null;
  let text = readFileSync(absolute, "utf8");
  if (relativePath === ".claude/CLAUDE.md") {
    const marker = text.indexOf(GENERATED_BLOCK_START);
    if (marker !== -1) {
      text = text.slice(0, marker);
    }
  }
  return text;
};

/** Inline code spans, plus the lines of every fenced ```bash / ```sh block. */
const extractCandidates = (text) => {
  const candidates = [];
  const withoutFences = [];
  let inFence = false;
  for (const line of text.split("\n")) {
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) {
      withoutFences.push(line);
      continue;
    }
    for (const span of line.matchAll(/`([^`\n]+)`/g)) {
      candidates.push(span[1]);
    }
  }
  for (const span of withoutFences.join("\n").matchAll(/`([^`\n]+)`/g)) {
    candidates.push(span[1]);
  }
  for (const line of withoutFences) {
    candidates.push(line.trim());
  }
  return candidates;
};

const isCheckablePath = (token) => {
  if (!token || NON_PATH.test(token)) return false;
  if (token.includes("://")) return false;
  const cleaned = token.replace(/\/+$/, "");
  if (!cleaned) return false;
  const [head] = cleaned.split("/");
  if (REPO_ROOT_FILES.has(cleaned)) return true;
  if (!REPO_ROOTS.has(head)) return false;
  return /[./]/.test(head) || cleaned.includes("/");
};

const collectMakeTargets = (makefilePath) => {
  const targets = new Set();
  if (!existsSync(makefilePath)) return null;
  for (const line of readFileSync(makefilePath, "utf8").split("\n")) {
    if (line.startsWith("\t") || line.startsWith("#")) continue;
    const match = /^([^\s:=#][^\s:#]*):(?!=)/.exec(line);
    if (match) targets.add(match[1]);
  }
  return targets;
};

const parseMakeInvocation = (token) => {
  const match = /^make\s+(?:-C\s+([\w./-]+)\s+)?([A-Za-z0-9_.%-]+)$/.exec(token);
  if (!match) return null;
  return { directory: match[1] ?? ".", target: match[2] };
};

const errors = [];
const checkedPaths = new Set();
const checkedMakeTargets = new Set();

for (const document of SCANNED_DOCUMENTS) {
  const text = readDocument(document);
  if (text === null) {
    errors.push(
      `routed document is missing: ${document} — this is how the 2026-09-27 DOC-19 failure happened; restore it or re-point the routing`,
    );
    continue;
  }
  const documentDir = dirname(join(ROOT, document));

  for (const token of extractCandidates(text)) {
    const make = parseMakeInvocation(token);
    if (make) {
      const makefileRelative =
        make.directory === "." ? "Makefile" : `${make.directory}/Makefile`;
      const makefilePath = join(ROOT, makefileRelative);
      const targets = collectMakeTargets(makefilePath);
      const key = `${makefileRelative}#${make.target}`;
      if (checkedMakeTargets.has(key)) continue;
      checkedMakeTargets.add(key);
      if (targets === null) {
        errors.push(
          `${document}: \`${token}\` needs ${makefileRelative}, which does not exist`,
        );
      } else if (!targets.has(make.target)) {
        errors.push(
          `${document}: \`${token}\` names a target that ${makefileRelative} does not declare`,
        );
      }
      continue;
    }

    if (!isCheckablePath(token)) continue;
    const relativePath = token.replace(/\/+$/, "");
    if (checkedPaths.has(relativePath)) continue;
    checkedPaths.add(relativePath);
    if (!existsSync(join(ROOT, relativePath))) {
      errors.push(`${document}: \`${token}\` does not exist`);
    }
  }

  // Markdown link targets resolve relative to the document, not the repo root.
  for (const link of text.matchAll(/\]\(([^)\s]+)\)/g)) {
    const target = link[1];
    if (!target || /^[a-z]+:/i.test(target) || target.startsWith("#")) continue;
    if (NON_PATH.test(target)) continue;
    const resolved = resolve(documentDir, target);
    if (!existsSync(resolved)) {
      errors.push(
        `${document}: link target \`${target}\` does not exist (resolved to ${resolved.slice(ROOT.length + 1)})`,
      );
    }
  }
}

const pathCount = checkedPaths.size;
const makeCount = checkedMakeTargets.size;

if (process.argv.includes("--verbose")) {
  for (const relativePath of [...checkedPaths].sort()) {
    console.log(`  path   ${relativePath}`);
  }
  for (const key of [...checkedMakeTargets].sort()) {
    console.log(`  make   ${key.replace("#", " -> ")}`);
  }
}

if (errors.length > 0) {
  console.error(
    "Release blocked: agent routing points at paths or targets that do not exist.",
  );
  for (const error of errors) console.error(`  - ${error}`);
  console.error(
    "Fix the routing document, or restore the target. Do not silence this check.",
  );
  process.exit(1);
}

console.log(
  `Agent routing OK: ${pathCount} paths and ${makeCount} make targets across ${SCANNED_DOCUMENTS.length} documents all resolve.`,
);
