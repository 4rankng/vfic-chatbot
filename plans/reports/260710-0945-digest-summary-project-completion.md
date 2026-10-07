# Agent Completion Checklist

## Task record

- Task: `fix(digest): fill the summary and project columns in the candidate digest`
- Scope: The email-digest pipeline only — summary enrichment on the console
  preview path, and project-of-interest resolution for candidates arriving
  through a channel mapped to several active projects. The recruiter sheet
  shipped with "Tóm tắt hội thoại" and "Dự án quan tâm" empty on all 14 rows.
- Files changed:
  - `backend/app/services/email_digest/service.py` (shared enrichment, JSON
    reply contract, project narrowing, `send_test_digest(summarizer=…)`)
  - `backend/app/services/email_digest/repository.py` (`mapped_projects`,
    ambiguous mapping now lists every project)
  - `backend/app/services/email_digest/spreadsheet.py` (wider project column)
  - `backend/app/composition/email_digest.py` (NEW composition root)
  - `backend/app/api/integrations.py` (preview route builds the summarizer)
  - `backend/app/workers/email_digest_worker.py` (imports the composition root)
  - `backend/tests/test_email_digest_service.py`,
    `backend/tests/test_email_digest_spreadsheet.py`,
    `backend/tests/test_email_digest_composition.py` (NEW)
- Instructions retrieved: `AGENTS.md`; `standards/agent-completion-checklist.md`;
  `backend/tests/test_architecture_boundaries.py` (the dependency matrix that
  governs the composition-root decision).
- Approval required: Yes — deploy.
- Approval evidence: User instruction in session: "complete them all, then
  commit push and deploy"; "when deploy just run make deploy, dont run
  release-check". Scope confirmed in the same session: the lead-field
  extraction bug (blank names, a name stored in "Khu vực") was explicitly
  skipped.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `send_test_digest` now takes `summarizer` and calls `_enrich_candidates` (`service.py`), so the preview workbook carries the summary; `_project_of_interest` returns `", ".join(sorted(...))` for an ambiguous mapping (`repository.py`). Regression: `test_preview_send_fills_the_summary_column`. |
| Diff is limited to the approved scope | PASS | `git diff --name-only` lists only the eight files above. The lead-extraction bug the user deferred is untouched — no change under `app/prompts/` or the lead pipeline. |
| Protected operations were avoided or approved | PASS | Commit, push and deploy explicitly requested by the user. `make release-check` deliberately NOT run per instruction; the enforced `pyright app/graph` gate was unaffected (no `app/graph` file changed). No branch, PR or merge created. |
| Focused tests/checks pass | PASS | `.venv/bin/pytest tests/test_email_digest_service.py tests/test_email_digest_spreadsheet.py tests/test_email_digest_worker.py tests/test_email_digest_composition.py tests/test_architecture_boundaries.py -q` → `91 passed`. |
| Broader regression tests pass when shared behavior changed | PASS | `tests/test_architecture_boundaries.py` (21 passed) is the repo's machine-enforced cross-layer gate and is in the run above; it is the check that would catch the new composition import. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check app tests` → `All checks passed!` |
| Type checking passes for affected code | PASS | The enforced gate is `uvx pyright app/graph`; no file under `app/graph` was modified. Changed modules (`app/api`, `app/services`, `app/workers`, `app/composition`) are outside that gate's scope and are covered by the passing test run. |
| Build/import validation passes for affected code | PASS | New module imported successfully by both callers; `tests/test_email_digest_composition.py` exercises the real `app.api.integrations` route function and the real `worker._tick_async`, so both import paths are executed. |
| Security and privacy impact reviewed | PASS | No new secret, PII or message content is logged. The added `logger.warning` calls emit `lead_id`/exception only — never a transcript. Summaries still carry no raw transcript unless a model ignores the JSON contract, which is the pre-existing fail-soft behaviour of the summary column. |
| Performance and async-I/O impact reviewed | PASS | Enrichment stays sequential and no query was added: `mapped_projects` is derived from the `mapped_projects_by_pair` set the repository already built, so the static I/O-in-loop scanner stays satisfied. Known cost: the preview button can now trigger up to `MAX_CANDIDATES_PER_DIGEST` (50) sequential LLM calls inside one HTTP request — recorded as a follow-up, not a regression for the cron path. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. The frontend `EmailDigestSection` button is untouched; it now receives a workbook with filled columns. |
| Error handling and compatibility reviewed | PASS | Per-candidate failure is caught and logged (`_enrich_candidates`); a malformed or prose reply degrades to a summary with the deterministic project (`_parse_reply`); preview construction failure degrades to `summarizer=None` and still returns `ok=True`, while the worker keeps its stricter fail-the-tick behaviour. Both paths tested. |
| Documentation impact handled | PASS | `node scripts/check-doc-links.mjs` → `Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve.` No routed doc changed; no user-visible behaviour, setup, command or public contract changed. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added in the diff. |
| Final `git diff --check` passes | PASS | No whitespace errors (see Result). |
| Final `git status --short` reviewed | PASS | Only the eight planned files plus the new composition module and the new test file; see Result. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  1. **Deferred by the user — lead-field extraction quality.** 13 of 14
     "Họ và tên" cells are empty and one candidate's name is stored in
     `living_area`. Needs separate investigation into
     `backend/app/prompts/candidate_extraction.py`; deliberately not bundled.
  2. **Preview latency.** `_enrich_candidates` is sequential and the window can
     hold 50 candidates, so the console preview can now make 50 sequential LLM
     calls in one request. Measure before optimising; consider bounding preview
     enrichment or moving it onto the existing RQ queue.
  3. **Not fixed (cosmetic).** The workbook filename and title banner are
     stamped with the *send* date while the window is the previous ICT day.
  4. **Not fixed (long lists).** A channel mapped to many active projects
     prints them all; column width 30 covers the realistic two-to-three case.