# Project-scoped KB — 2026-10-01

## Result

The nine category contracts and their backend/frontend authoring templates no longer contain `job_ids`. The misspelling `jobs_ids` is retired too. Categories belong to the Project and can validate, prepare or activate independently of Jobs. The one-file training pipeline retains administrator order, prepares privately, and publishes a coherent project snapshot. Replacing Jobs replays active sibling facts without reference validation or authoring order dependencies.

Legacy Markdown, JSON payloads, inline arrays, dash lists, rendered category chunks and exact/semantic/coalesced cached evidence are normalized at the value boundaries. New category and direct-page writes store clean source. Category/editor reads, the focused direct-context prompt, fresh RAG citations, caches, document chunk/digest responses, search previews, source downloads and all three export authority branches omit the retired structural fields. Factual prose, ordinary record IDs, citations, RQ receipts and unrelated identifiers are preserved. A Markdown or JSON source containing only retired fields is empty and cannot produce a misleading download or direct-page write. Original parser/request limits are applied before cleanup.

Derived roles receive project facts. Salary, age, gender, experience and accommodation/meal scalars are published only when all category records agree; conflicts or missing values remain unknown. Zero salary is retained. Complete records remain retrievable, and requirements, schedules, benefits and transportation retain all project records. This avoids assigning whichever conditional record appears last to every role.

Boundary normalization was selected over rewriting historical data: old immutable source, upload bytes, payloads, checksums, embeddings, publication checkpoints and rollback snapshots retain their identity. New writes and user/bot-facing knowledge are clean. PostgreSQL regressions prove old payloads still cut over and roll back without mutating stored identity. Historical migrations and historical audit reports remain frozen.

A final independent review found and fixed the remaining document chunk/digest response gap and a citation fallback bug: a quote emptied by cleanup now falls back to factual chunk content while keeping useful summaries. New regressions cover source downloads, nested reference-only JSON, output nonmutation and this fallback.

The expanded type audit repaired 24 schema variance diagnostics and 16 diagnostics in affected orchestration/projection code without disabling checks. The typing repair preserves all thirteen *post-removal* public JSON schemas. New quality receipts accurately report `schema_check`. Missing projects fail before projection writes, wrong category models fail before I/O, and a training source without a project cannot stage. Batch and per-item embedding behavior are covered by regressions.

## Scope and instructions

This change extends the authorized broad audit and KB export work. It changes category schemas/templates, parsing/validation, training/projection orchestration, compatibility transformations, admin read/export boundaries, chatbot evidence, frontend serialization and regression tests. No branch, commit, push, PR, merge, deployment, dependency update or schema migration was performed. No live provider or production connection was used.

Retrieved instructions: root and frontend AGENTS, relevant code standards/testing, the architecture dependency matrix, system/API/KB workflow sources, bot response routing, and the sixteen-gate completion template. UI changes are confined to existing questionnaire/serialization contracts and use the installed editor/download controls.

## Verification

- Full backend regression suite: **3196 passed, 37 existing optional tests skipped**, 147.16s. Command: `.venv/bin/python -m pytest tests --ignore=tests/integration -q -rs`. Evidence: `/tmp/vfic-project-kb-reference-backend-unit-delivery.log`. Skips require opt-in live Jev replay, a missing captured RAG embedding baseline, or unavailable pinned Caddy/Redis probe images/Caddy binary. None of the affected KB or architecture checks is skipped.
- Full PostgreSQL suite: **295 passed**, 292.21s, including migration round-trip/reversal and existing lifecycle/concurrency regressions. After the final guard/type refinements, the affected KB suite was rerun: **92 passed**, 45.26s. Evidence: `/tmp/vfic-project-kb-reference-backend-pg-all.log` and `/tmp/vfic-project-kb-reference-backend-pg-frozen.log`. Disposable loopback PostgreSQL16+pgvector and Redis were used; only task-owned containers were removed afterward.
- Final owner-focused regression checks also passed **153 unit/architecture** and **43 PostgreSQL** cases; compatibility/output owner checks passed **75 unit/architecture** and **1 PostgreSQL** case. These overlap the full suite. Source normalization, original size limits, reference-free templates, independent category activation before Jobs, safe shared scalar projection, retained training plans, stale evidence caches, export emptiness and immutable rollback are covered.
- Full frontend suite: **894 tests/118 files passed**. App and Node TypeScript checks pass. Full ESLint has **0 errors and 35 existing warnings**; scoped changed-file checks pass. Registry232 paths pass. Production build and built-bundle browser smoke pass. Evidence: `/tmp/vfic-project-kb-reference-frontend-all.log`, `...-frontend-types.log`, `...-frontend-lint.log`, `...-registry.log`, and `...-build.log`.
- Real desktop/mobile Chrome: **4 tests passed**. The browser uploads old fields, reads the cleaned editor, downloads actual UTF-8 KB bytes, preserves the unsaved editing buffer, tests empty RAG handling and verifies the full blank template has no reference fields. Both contexts exercise390/900/1440px widths, keyboard activation and horizontal overflow. Evidence: `/tmp/vfic-project-kb-reference-e2e.log`.
- Expanded Pyright across graph, domain helpers, knowledge output/category schemas/contracts/parser/projections/lifecycle/batch/training and export: **0 errors, 0 warnings**. Ruff across the backend passes; `uv lock --check` passes. Routing checker verifies32 paths and4 make targets across4 documents. Final whitespace and status checks pass. Evidence: `/tmp/vfic-project-kb-reference-backend-types-delivery.log`, `...-backend-lint-delivery.log`, `...-lock.log`, `...-doc-links-final.log`.

Final focused boundary checks passed **146 tests** covering the latest source/output/cache regressions (including original size limits and architecture). Evidence: `/tmp/vfic-project-kb-reference-final-boundaries.log`.

Initial check failures were resolved rather than hidden: typed schema/base variance, nullable projection/training state and callable embedding annotations were repaired; two newly written PostgreSQL fixture queries were corrected. Final checks above pass. The aggregate release wrapper requires a clean committed checkout, so its relevant constituent checks were run while preserving the user's unstaged workspace.

## Portable artifacts and limits

The full `plans/exports/2026-10-01-project-scoped-kb.patch` includes all prior audit/export changes and this change against `35d970689cbb092e4f9100f1e60305c9bd7505ed`. The separate incremental patch targets the previous `2026-10-01-project-kb-export.patch` (SHA256 `5044e3a453c5ecdd25b8f1102939dec0d197c52b83b4472359cf16120b383f2b`). Apply one of these options, not both. The predecessor patches are preserved.

Export verification uses a temporary Git index and a fresh original-base archive: check/apply, exact file bytes and executable modes, reverse apply, and unchanged real HEAD/index/status. Each artifact has a manifest, checksum and diffstat; application instructions are in `plans/exports/PROJECT-SCOPED-KB-PATCH-README.md`.

This is local regression and browser proof. Live providers, deployed behavior, production, Safari/Firefox and the optional external/edge/captured-corpus checks were not exercised. Historical rows are intentionally retained rather than physically purged. Original broader UI/recruitment improvements remain part of the full patch and their earlier reports remain historical evidence.
