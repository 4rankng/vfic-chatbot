# KB Upload — md/txt/docx + paste-text — Completion

## Task record

- Task: Ensure KB upload accepts .md/.txt/.docx and supports pasted text on
  every surface; plus prod diagnosis of failed bot sends (Zalo OA token).
- Scope: backend extract-text endpoint; frontend single-page .docx pre-fill;
  paste-text disclosure on RAG ingest strip, migration section, and project
  creation brief import. No changes to bot send/circuit-breaker behavior
  (operator confirmed the 2-failure circuit breaker is correct).
- Files changed: 15 modified + 3 new (see `git status --short` at commit).
- Instructions retrieved: AGENTS.md, frontend/AGENTS.md,
  docs/troubleshooting/README.md, docs/ops/incident-runbook.md.
- Approval required: deploy approved by operator in-session ("commit, push and
  deploy to prod"). Circuit-breaker change explicitly declined by operator.
- Approval evidence: session transcript 2026-10-07.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | .md/.txt/.docx already accepted on upload lanes (file_extraction.py); new `POST /knowledge/documents/extract-text` powers single-page .docx pre-fill; paste wraps text as `van-ban-dan.md` and rides the existing ingest chain on all three surfaces |
| Diff is limited to the approved scope | PASS | `git status --short` shows only knowledge-upload files + registry manifest |
| Protected operations were avoided or approved | PASS | No Alembic migration, no prompt/bot-safety change, no dependency change; deploy explicitly requested |
| Focused tests/checks pass | PASS | backend `.venv/bin/pytest tests/test_knowledge_extract_text_endpoint.py tests/test_upload_size_guard.py tests/test_recruitment_only_knowledge_api.py` → 15 passed |
| Broader regression tests pass when shared behavior changed | PASS | frontend `npx vitest run src/components/atomic-crm/projects` → 25 files / 351 tests passed |
| Lint passes for affected code | PASS | `npm run lint` → 0 errors (35 pre-existing warnings) |
| Type checking passes for affected code | PASS | `npm run typecheck` clean |
| Build/import validation passes for affected code | PASS | `npm run registry:gen` → +4 manifest entries; `npm run registry:check` runs in pre-commit; `npm run build` exercised via deploy image build |
| Security and privacy impact reviewed | PASS | New endpoint admin-gated (`require_admin`), stateless (no persistence), bounded by `read_upload_within_limit` (20 MiB) and reuses the strict format contract; no secrets logged |
| Performance and async-I/O impact reviewed | PASS | Endpoint is fully async, OOXML guards (zip-bomb limits) shared with the existing upload path; paste reuses the same worker pipeline, no new queue traffic shape |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | PasteTextArea labelled (`aria-label`, `aria-expanded` trigger, disabled states); copy in Vietnamese; React Aria stays inside `.uu-scope`; no Radix/React-Aria nesting introduced |
| Error handling and compatibility reviewed | PASS | Extraction rejections surface Zalo-style structured `errors` detail (422); oversized pick rejected client-side; stale-read guards preserved in the draft hook |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK"; knowledge.py module docstring updated for the new route; no routing change |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | grep over changed files: none |
| Final `git diff --check` passes | PASS | clean |
| Final `git status --short` reviewed | PASS | 15 modified + 3 new files, all in scope |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - Prod incident (bot sends failing) was an operator credential issue: Zalo OA
    access/refresh tokens for the `tingting` account. Tokens re-entered and
    verified live (`getoa` ok, OA 3383849659955472174); stuck threads resumed
    via the designed take-over → release flow. No code change.
  - Follow-up (operator decision): the singleton `zalo_oa_*` (default) account
    keys refreshed successfully on 2026-10-07 09:15 while the `:tingting` pair
    was dead — if both pairs belong to the same OA, any default-account refresh
    can burn the shared single-use refresh chain. Worth confirming whether the
    default OA credentials are still needed.
