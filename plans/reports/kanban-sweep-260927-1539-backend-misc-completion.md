# Kanban sweep 260927-1539 — backend misc cards PERF-18, ARCH-30, ARCH-31 — completion report

## Task record

- Task: Implement kanban cards PERF-18, ARCH-30, ARCH-31 (lane-backend-misc).
- Scope: one backend query-shape fix, one behavior-preserving flattening, one dead-code
  deletion (two exports), with regression tests where warranted. No commit, no `git add`.
- Files changed:
  - `backend/app/services/knowledge/category_projections.py` — PERF-18 batched fetch
  - `backend/app/services/profile_enrichment.py` — ARCH-31 flatten
  - `frontend/src/components/atomic-crm/personas/domain/personaMarkdown.ts` — export removed
  - `frontend/src/components/atomic-crm/reporting/domain/performanceDiagnostics.ts` — export removed
  - `backend/tests/test_category_projections_sibling_batch.py` — new (2 tests)
  - `backend/tests/test_messenger_profile_enrichment.py` — new (5 tests)
- Instructions retrieved: AGENTS.md, the three kanban cards, both target source files,
  `category_contracts.py` signatures, `models/knowledge.py` (revision PK), existing
  integration tests (`test_project_category_activation.py`), existing enrichment test
  fakes (`test_profile_enrichment.py`).
- Approval required: none triggered (no migrations, no webhook/auth/security changes, no
  dependency changes, no deployment, no prompt/persona/safety changes).

## ARCH-30 re-verification outcome (deviation from card, per card instruction)

The card's premise — five zero-reference items — was **wrong for three of the five**.
Re-verification before deleting (plain recursive grep over `frontend/src`, 2026-09-27):

| Item | Re-verification result | Action |
|---|---|---|
| `frontend/src/components/admin/confirm.tsx` | **4 live importers**: `admin/simple-form-iterator.tsx:41`, `atomic-crm/knowledge/KnowledgeSourceList.tsx:9`, `atomic-crm/conversations/presentation/ConversationShow.tsx:13`, `atomic-crm/users/UserActions.tsx:9` | **Left in place** |
| `frontend/src/components/admin/icon-button-with-tooltip.tsx` | **1 live importer**: `admin/simple-form-iterator.tsx:42` | **Left in place** |
| `frontend/src/lib/field.type.ts` | **10 live importers** (boolean/text/date/image/url/file/badge/email/number/select-field.tsx under `components/admin/`) | **Left in place** |
| `hasPersonaFollowupRules` in `personaMarkdown.ts` | zero references outside its defining file | **Deleted** (plus its now-unused `PersonaFollowupRules` type import) |
| `getEndToEndMetric` in `performanceDiagnostics.ts` | zero references outside its defining file | **Deleted** (plus now-unused `PerfMetrics` type import) |

The repowise `in_degree=0` claims for the three files are refuted by direct grep; the
card itself noted the TypeScript call-edge resolution basis runs 44% guessed, which is
exactly why it demanded re-verification before deleting.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | PERF-18 and ARCH-31 complete; ARCH-30 complete for the two verifiably dead exports; the three referenced files left in place and reported (see table above). |
| Diff is limited to the approved scope | PASS | Two backend source files, two frontend domain files, two new colocated test files. Nothing else touched by this lane. |
| Protected operations avoided or approved | PASS | No migrations, webhooks, auth, CORS, rate limits, protected paths, prompts, or dependency changes; no commit/add/push by this lane. |
| Focused tests pass | PASS | `pytest tests/ -k "knowledge or projection"` → **206 passed, 1 skipped**; new `test_category_projections_sibling_batch.py` → **2 passed**; `test_messenger_profile_enrichment.py` → **5 passed**; enrichment set (test_profile_enrichment, test_lead_gender_guard, test_persistence_worker, test_backfill_oa_profiles, test_zalo_multi_oa) → **69 passed**. |
| Broader regression tests pass when shared behavior changed | PASS | Full unit suite `.venv/bin/pytest -m "not integration" -q -p no:randomly` → **2542 passed, 24 skipped**. REL-05 regression guards (`test_lead_gender_guard.py`, "Regression guards for REL-05 — the blank-only gender rule must be atomic") pass **untouched**. |
| Lint passes for affected code | PASS | `backend/.venv/bin/ruff check .` → **All checks passed** (run twice: mid-session and after the last file write). |
| Type checking passes for affected code | PASS (with caveat) | `tsc --noEmit -p tsconfig.app.json` reports errors **only** in `frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.test.tsx` (5 errors) — an **untracked file owned by another active lane** (in-flight knowledge work). Zero errors in my two edited files or any importer. My deletions introduce no type errors; full-tree clean typecheck is blocked only by that foreign in-flight file. |
| Build/import validation passes for affected code | PASS | `py_compile` on all four touched backend files → OK. Frontend import-graph check: `vitest run src/components/atomic-crm/personas src/components/atomic-crm/reporting` → **8 files / 24 tests passed** (import resolution included). |
| Security and privacy impact reviewed | PASS | No secrets/PII/message content introduced; dead exports removed carry no data; enrichment refactor preserves the blank-only guards that protect candidate-stated gender. |
| Performance and async-I/O impact reviewed | PASS | PERF-18 is the perf fix itself: one `select … id IN (keys)` replaces N per-sibling `db.get` round-trips on the jobs-cutover path; empty-sibling case issues no revision query (matches old zero-iteration behavior); all I/O remains async via `db.scalars`. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI changes (dead-export removal only, no behavior). |
| Error handling and compatibility reviewed | PASS | None-guard preserved: a sibling revision that vanishes between the sibling fetch and the batch read is skipped, not a crash (regression-tested). Messenger behavior contract preserved field-for-field (same guard order, same blank-only writes, same settled logic, same event order sorted by lead id). |
| Documentation impact handled | N/A | No user-visible behavior, setup, command, or architecture change; dead-export removal and internal refactor only. |
| No new unlinked TODO/FIXME/HACK | PASS | None added. |
| Final `git diff --check` passes | PASS | Clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | This lane's residue: 2 modified frontend domain files (uncommitted), 2 untracked backend test files. Pre-existing from others: `.claude/CLAUDE.md`, `plans/reports/kanban-sweep-260927-1539-docs-completion.md` modified, another lane's untracked `personas/presentation/` and `use-project-knowledge-catalog.test.tsx`, kb/pencil staged deletions. No git add/commit run by this lane. |

## Notes for the lead

1. **Parallel session committed my backend edits**: commit `503051c2` ("check in the parallel
   session's in-flight backend work and docs sweep") includes my PERF-18 and ARCH-31 source
   edits and the sibling-batch test file. Contents verified intact post-commit (grep +
   full suite rerun on the committed tree state). The two frontend domain-file edits and the
   messenger test file remain uncommitted working-tree changes.
2. **Completion-checklist template missing**: `standards/agent-completion-checklist.md` no
   longer exists in the tree (the docs lane's sweep moved/renamed the `standards/` surface),
   so this report mirrors the sibling lane's gate-table format. Evidence per gate is included.
3. **Typecheck caveat**: the only typecheck failures belong to another lane's untracked
   in-flight test file; they predate and are independent of my deletions.

## Result

- Overall status: **DONE** (ARCH-30 executed per its own "leave and report" instruction for
  the three referenced files).
- Follow-up: ARCH-30's card premise should be re-carded — the three files are alive; only
  the two exports were dead. Also worth noting for the re-card: if the admin kit upstream
  (shadcn-admin-kit) is the intended eventual replacement surface for `confirm.tsx` /
  `icon-button-with-tooltip.tsx`, the reference from `simple-form-iterator.tsx` and the
  atomic-crm importers settles their status as vendored framework code in active use.
