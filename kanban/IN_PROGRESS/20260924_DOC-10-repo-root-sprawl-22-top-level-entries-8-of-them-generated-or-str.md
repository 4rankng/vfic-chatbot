---
id: DOC-10
title: "Repo-root sprawl — 22 top-level entries, 8 of them generated or stray"
severity: medium
area: docs
labels: [documentation, tech-debt]
effort: S
status: in_progress
column: TODO
opened: 2026-09-24
---

# DOC-10 — Repo-root sprawl — 22 top-level entries, 8 of them generated or stray

**Severity:** medium · **Area:** docs · **Effort:** S · **Labels:** documentation, tech-debt

**Trạng thái:** TODO

## Problem

The repository root carries 22 top-level entries, eight of which are generated output, stray design or source files, or empty templates — `openwiki/`, `repomix-output.xml`, `assets/showoff/`, `pencil/`, `kb/`, `lessons/`, `design-qa.md` and the half-tracked `plans/`. A root `README.md` that `docs/codebase-summary.md` claims exists does not.

## Evidence

- Source and ops to keep: `backend/`, `frontend/`, `docs/` (77 entries / 5 subtrees), `standards/` (9 files), `scripts/`, `Makefile`, `.github/`, `AGENTS.md`, `CLAUDE.md`, `TECH.md`, `.gitignore`, `.openwikiignore`.
- Generated or stray: `openwiki/` (~45 files, generated and wrongly briefed — DOC-01), `repomix-output.xml` (4.8 MB — DOC-06), `assets/showoff/` (21 entries, ~21.2 MB — DOC-07), `pencil/` (2 `.pen` files, 77.3 + 89.1 KB), `kb/` (9 files incl. `RAW-Lich trinh xe bus.pdf` 284.1 KB and `RAW-AI.docx` 11.8 KB for the retired LG Display project), `lessons/` (`README.md` 3.6 KB, template-only, "_No lessons recorded yet._"), `design-qa.md` (10.5 KB, loose design-QA report) and `plans/`.
- `docs/codebase-summary.md:85` shows a root `└── README.md` that is absent from both the root listing and `.git/index`.
- `lessons/` duplicates the `docs/decisions/` + `docs/troubleshooting/` destinations that `docs/decisions/README.md:68` itself points to.

## Impact

Navigation and agent-context cost at the exact place every session starts, plus ~27 MB of stray tracked weight that has nothing to do with the product.

## Suggested fix

Keep the root to source + docs + ops: move `pencil/`→`design/`, `kb/`→`docs/kb-seed/` (or `backend/tests/fixtures/`), `assets/showoff/` out of the repo or under `docs/assets/` after webp conversion, `design-qa.md`→`docs/`, and either populate or delete `lessons/`. Add the missing root `README.md`.

## Notes

Also folds two low findings that need no ticket of their own. **F14 stale remote refs** — `.git/packed-refs` has `refs/remotes/origin/main` packed at the old `08621c4` while the loose ref and local `main` are `923b1d3`, plus 15 stale Dependabot branches, two of them majors (`react-router-8.3.0`, `vitest-4.1.11`); fix with `git remote prune origin` after deciding the two majors, then `git gc --prune=now` if the pack does not shrink. **F17 unmanaged journals** — `docs/journals/` holds 38 files with no index and `AGENTS.md` never routes to it, while `docs/brainstorms/` (2) and `docs/research/` (1) are unindexed too; add `docs/journals/README.md` with a date/topic/commit table, or fold journals into `docs/decisions/` and delete `lessons/`.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
