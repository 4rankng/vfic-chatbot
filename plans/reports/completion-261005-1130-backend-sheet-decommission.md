# Agent Completion Report — Backend Google Sheet decommission

Filled from `standards/agent-completion-checklist.md`. Plan ticket:
`plans/261005-0327-kb-workspace-overhaul/phase-07-backend-sheet-decommission.md`
(owner authorized: "remove and clean up google sheet completely").

## Task record

- Task: remove the server-side Google Sheet sync feature the console stopped
  using in the morning session (routes, services, workers, cron, config,
  models, tables, tests, docs).
- Scope: `backend/app/api/knowledge.py|projects.py`, `app/models/*` (2 deleted +
  `__init__`), `app/schemas/knowledge.py` + `project_single_page_sync.py`
  (deleted), `app/services/knowledge/external_source_sync/**` +
  `external_source_admin.py` + `services/project/single_page_external_sources.py`
  (deleted), `services/project/service.py`, `app/workers/*` (2 deleted),
  `app/composition/project_knowledge_jobs.py`,
  `app/project_knowledge/application/jobs.py`, `app/main.py`,
  `app/core/config.py`, `app/reporting/infrastructure/performance_dashboard.py`,
  migration 0067 (new), 10 test files deleted, 4 test files adjusted, 4 docs.
- Files changed: `81e8a312` (backend) and `abb14b96` (docs).
- Instructions retrieved: root `AGENTS.md`, backend lane via Makefile,
  runtime-surface snapshot procedure from session memory
  (`runtime-surface-snapshot-diffing`).
- Approval required: yes — the owner explicitly authorized full removal after
  the parked-ticket explanation.
- Surface facts source: backend scout report (all 8 routes, call chain
  scheduler → tick → enqueue → worker → sync, config knobs, oracles).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `rg "external_source\|ExternalSource\|kb_sync_cron" backend/app` → zero hits; single alembic head `0067_drop_external_source_sync`; `import app.main` OK. |
| Diff is limited to the approved scope | PASS | Both commits touch only the Sheet surface, its tests/pins, and the four docs. `email_digest/spreadsheet.py` and `project/external_api.py` verified as unrelated features and left alone. |
| Protected operations were avoided or approved | PASS | No destructive git; no deploy; **the data-destructive step ships as migration 0067, not applied here** — `pg_dump` before `make deploy` is the owner's pre-deploy step (also in the migration docstring). |
| Focused tests/checks pass | PASS | Runtime-surface suite 5/5 after re-pinning; boundary + performance suites adjusted and green. |
| Broader regression tests pass when shared behavior changed | PASS | Full backend unit lane: **3,622 passed, 28 skipped** (ruff clean, exit 0). Frontend projects/performance/reporting cross-check: 368 passed. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check .` clean. |
| Type checking passes for affected code | PASS | Pyright on the 8 touched modules: 5 errors, byte-identical to the HEAD baseline of the same file (verified against a `git show HEAD:` copy) — zero new. |
| Build/import validation passes for affected code | PASS | `python -c "import app.main"` OK; `alembic heads` single head; migration file AST-parses. |
| Security and privacy impact reviewed | PASS | Removal shrinks the attack surface (SSRF-hardened fetch path gone). The dropped tables held sync configs, not candidate PII; the PII guard test for those fixtures went with them. Published category revisions were never FK-bound and survive. |
| Performance and async-I/O impact reviewed | PASS | One fewer cron tick pair on the maintenance scheduler; the dashboard drops one concurrent read (gather list shrank accordingly, `_T` TypeVar restored). |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | Backend only; the console surface was removed in the morning session. |
| Error handling and compatibility reviewed | PASS | 0048-style rate-limit and conflict imports pruned where they became unused; `_SINGLE_PAGE_SOURCE_BAD_REQUESTS` mapping removed with its routes; no dangling imports (ruff). |
| Documentation impact handled | PASS | Guide, PDR, system-architecture and incident-runbook updated; runbook revision-rollback SQL kept under a neutral heading; `node scripts/check-doc-links.mjs` → OK. |
| No new unlinked TODO/FIXME/HACK | PASS | None added. |
| Final `git diff --check` | PASS | Clean. |
| Final `git status --short` reviewed | PASS | Clean after both commits. |

## Deploy note (operator)

Migration 0067 drops both sync-state tables **with their rows**. Run
`pg_dump` on production before `make deploy`; the owner runs deploys, so the
backup has not been taken from here. `downgrade()` recreates both tables empty
so a rollback deploy cannot hit missing-table errors.

## Runtime-surface attribution

Route counts `knowledge` 18→14 and `projects` 29→25; the boundary fixture lost
exactly 4 rows (two `jobs.py` enqueue scopes, two worker `enqueue_one_shot`
scopes); broad counts `provider_boundary` 100→95 (the sheet fetch path) and
`queue_producer` 37→29. The probe script (importing the test module's own
`_route_records`/`_runtime_calls`) reported **no unexpected new rows** — every
delta is this removal.
