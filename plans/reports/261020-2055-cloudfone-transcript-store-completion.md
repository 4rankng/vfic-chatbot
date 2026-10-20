# Agent Completion Checklist

Copy this file to
`plans/reports/<YYMMDD-HHmm>-<slug>-completion.md` for each implementation task.
Replace every `PENDING` with `PASS`, `N/A`, or `BLOCKED`. A task is not complete
while any item is `PENDING` or `BLOCKED`.

## Task record

- Task: Persist CloudFone call transcripts to the DB (transcribe once, reuse forever) + MiniMax-M3.1-Flash rollout safety
- Scope: store each STT transcript in `cloudfone_call_transcripts` so reruns/later analysis never re-download WAV or re-run STT; verify locally with real MiniMax-M3.1-Flash for a disruption-free prod deploy
- Files changed: backend/app/models/cloudfone.py (new), backend/app/models/__init__.py, backend/alembic/versions/0076_cloudfone_call_transcripts.py (new), backend/app/services/cloudfone_transcripts.py (new), backend/app/services/cloudfone.py, backend/tests/test_cloudfone_service.py, backend/tests/integration/conftest.py, backend/tests/integration/test_cloudfone_transcript_store.py (new)
- Instructions retrieved: user messages in session ("store the call transcript to db … we do it one and we store in db", "test locally with minimax see if it can work with the code, I want no disruption when deploy to prod", "use MiniMax-M3.1-Flash")
- Approval required: yes — feature addition beyond the original plan
- Approval evidence: session message requesting DB persistence + "do it properly" (ak:cook route accepted)

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Cache-first `_attach_transcripts`: stored transcript → no download, no STT; miss → download + STT + persist (per-call fail-soft). `DbTranscriptStore` on the worker session by default (production), `transcript_store` seam injectable. Live x2 smoke with real vendor + real MiniMax-M3.1-Flash (`/tmp/smoke_pipeline.py`, 2026-10-01 day): run 1 = `status=sent transcripts=4 insights=4 downloads=4 stt=4 stored=4` (real WAV downloads + real STT + rows persisted, header `Tổng cuộc gọi: 7 · Trả lời: 4 (57.1%)` verified); run 2 = zero downloads, zero STT (counters unchanged), `stored=4` unchanged, letter identical. Cached transcript sample: `S1: Alo | S2: alo chị ơi có anh…`. Letter clean of reasoning (`众所周`/`think` → 0). One transient provider `httpx.ReadTimeout` in run 1's daily-insights call was fail-softed by design (`build_daily_insights` → None → section omitted, letter sent) — resilience observed live. |
| Diff is limited to the approved scope | PASS | `git status --short` shows exactly the 8 files listed above (4 modified, 4 new); earlier feature work already committed as `0272372f` externally. |
| Protected operations were avoided or approved | PASS | No destructive ops; migration 0076 is additive (new table; `downgrade()` drops only it); no secrets logged. |
| Focused tests/checks pass | PASS | `pytest tests/test_cloudfone_service.py tests/test_cloudfone_worker.py tests/test_cloudfone_settings.py tests/test_runtime_surface_inventory.py -q` → 63 passed (incl. 5 new cache tests: hit-skip, persist-on-miss, fail-soft, rerun-0-STT, no-provider cache fill). `pytest tests/integration/test_cloudfone_transcript_store.py -q` → 2 passed against real PostgreSQL (migration 0076 to head + model roundtrip + unique `call_id` + session-usable-after-failure). |
| Broader regression tests pass when shared behavior changed | PASS | Full backend unit suite (`pytest -q -m "not integration"`) → 4079 passed, 28 skipped, 322 deselected. Inventory oracle recomputed: provider_boundary 113, digest `b323ba2b…` **unchanged** (store adds zero egress sites). |
| Lint passes for affected code | PASS | `ruff check app tests` → All checks passed. |
| Type checking passes for affected code | PASS | `uvx pyright` on models/cloudfone.py, services/cloudfone_transcripts.py, services/cloudfone.py, models/__init__.py → 0 errors; 2 pre-existing warnings (`ExternalSourceSyncState`/`SinglePageExternalSourceSyncState` stale `__all__` entries from migration 0067 era, untouched). |
| Build/import validation passes for affected code | PASS | Module imports exercised by the 63-test run and both integration tests; live smoke imported and ran the full pipeline. |
| Security and privacy impact reviewed | PASS | Transcripts (customer call content) land only in the existing app DB — same store as conversations/leads; no new egress; store code has no logging of transcript text. Retention noted as follow-up below. |
| Performance and async-I/O impact reviewed | PASS | One indexed SELECT + one small INSERT per call (vs ~13s STT each); rerun cost drops from minutes to milliseconds; per-save `commit()` keeps writes durable and bounded. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. |
| Error handling and compatibility reviewed | PASS | Cache read/write failures fail-soft per call (logged `cache read/write failed`, letter intact — tested); `save()` rolls back and re-raises so the session stays usable (integration-tested); unique `call_id` prevents duplicate rows; behavior with `transcript_store=None`/`db=None` identical to before (all pre-existing tests pass unchanged). |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve." No docs describe the STT pipeline internals (grep `GetCallHistoryVer2\|transcrib` in docs/ → 0 hits); module docstrings updated instead. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | grep over the 4 new files → 0 hits. |
| Final `git diff --check` passes | PASS | `git diff --check` → CLEAN. |
| Final `git status --short` reviewed | PASS | Exactly 4 modified + 4 untracked, all in the scope list above. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: (1) transcript rows are append-only with no retention policy — call content is PII; a TTL/retention sweep is a follow-up decision for the data owner. (2) `MINIMAX_ASR` quota still rides the shared M-plan pool; the cache makes reruns free, so only first-touch calls pay STT. (3) Pre-existing pyright warnings in `models/__init__.py` `__all__` (stale names) and one pre-existing error at `api/integrations.py:413` remain out of scope.
