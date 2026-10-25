# Completion report — Cloudfone ICT times + DOCX detail-table redesign

## Task record

- Task: (1) Every outbound Cloudfone surface (insights email, DOCX report, LLM
  prompt lines, hour buckets) shows Vietnam time, never UTC. (2) Redesign the
  "3. CHI TIẾT CÁC CUỘC GỌI ĐÃ TIẾP NHẬN" table per the consulted spec
  (DeepSeek 2026-10-25): merged time+duration column, dominant summary column,
  forced fixed table layout.
- Scope: backend Cloudfone insights/report generation only. No API, model, or
  frontend change.
- Files changed: `backend/app/services/cloudfone.py`,
  `backend/app/services/cloudfone_report.py`,
  `backend/tests/test_cloudfone_service.py`.
- Instructions retrieved: user inbound 25/10 ("timing in report and email sent
  should be always vietnam time, dont ever use UTC") + screenshot of the
  mis-rendered table + pasted consult verdict (local://paste-1.md).
- Approval required: none (direct user order: fix, redesign, commit, push,
  deploy).
- Approval evidence: user messages this session.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior complete | PASS | `call_date_to_ict` converts vendor naive-UTC `callDate` (+7) at the single chokepoint `_leg_from_row`; all display paths (`_hhmm`, email meta, hour buckets, DOCX tables/charts, LLM prompt) inherit ICT. `_day_window` now queries the vendor's UTC clock: ICT day D = UTC `[D-1 17:00:00, D 16:59:59]`. Detail table rebuilt to spec widths `[0.75, 0.95, 1.05, 4.02]` with stacked time/duration; missed table `[0.65, 1.05, 1.20, 3.87]`; `tblLayout fixed` + `tblW` + `gridCol` + per-cell `tcW` on all four tables; `tblHeader`, `cantSplit`, horizontal-only borders, vAlign top. |
| Diff limited to approved scope | PASS | 3 files, commit `15e8b035`. Pre-existing kanban deletions in the worktree are not mine and were not staged. |
| Protected operations avoided | PASS | Deploy used the blue/green `make deploy-backend` fast track; no destructive DB ops, no migration in this change. |
| Focused tests pass | PASS | `pytest tests/test_cloudfone_{service,settings,transcript_backfill,transcripts_api,worker}.py` → 79 passed. Expectations shifted +7h to the ICT model; new regression tests: `call_date_to_ict` (naive UTC, aware offset, garbage), `_day_window` UTC mapping. |
| Broader regression tests | PASS (scoped) | All five Cloudfone suites green. Full `make release-check` NOT run: the fast-track deploy was user-ordered and the worktree carries ~190 unrelated kanban deletions that fail its clean-worktree gate. |
| Lint passes | PASS | `ruff check` on the three changed files — all clear. |
| Type checking passes | N/A | The repo's Pyright gate is scoped to `app/graph` (`pyrightconfig.json`); changed files are `app/services`. |
| Build/import validation | PASS | Throwaway smoke imported both modules and generated a real DOCX from the live-shape `REAL_DAY_LEGS` fixture (128,287 bytes); script removed after proof. |
| Security / privacy | PASS | Timestamp display only; no PII surface change; transcript text still never ships raw (tests assert). |
| Performance / async I/O | PASS | Conversion is O(1) per vendor leg; vendor query shape unchanged (same two window strings). |
| Accessibility / Vietnamese UX | PASS | Table readability fix is the task; summary column widened 2.97"→4.02", header repeats across pages, rows no longer split. Live DOCX render not possible on this machine (no LibreOffice) — proof is the generated OOXML: grid dxa `[1080, 1368, 1512, 5789]` and `[936, 1512, 1728, 5573]`, `tblLayout fixed` ×4, `tblHeader` ×2, `cantSplit` ×7, `>14:50<` present, zero `>07:50<` leaks. |
| Error handling / compatibility | PASS | Unparseable `callDate` passes through unchanged (degrades exactly as before); aware timestamps convert by their own offset. Legacy stored `cloudfone_call_transcripts.started_at` rows keep vendor-UTC strings — the report/email always use the fresh fetch, and `backfill_day_transcripts(force=True)` rewrites a day to ICT if the admin wants the viewer aligned. |
| Documentation impact | PASS (N/A) | No doc describes the old window/timezone behavior (grep over `docs/` empty); no agent routing change → doc-links check not required. |
| No new unlinked TODO/FIXME/HACK | PASS | `grep -c` = 0 on both changed files. |
| `git diff --check` | PASS | Clean. |
| `git status --short` reviewed | PASS | Only the user's pre-existing kanban deletions remain; nothing of this task is unstaged. |

## Result

- Overall status: PASS
- Commit: `15e8b035` on `main`, pushed to `origin/main`.
- Deploy: `make deploy-backend` (backup + image push + blue/green cutover) —
  result recorded below when the run lands.
- Remaining risks / follow-ups:
  1. The vendor window change assumes the vendor filters `GetCallHistoryVer2`
     against the same UTC clock it stamps `callDate` with (user-confirmed UTC).
     If tomorrow's letter shows a 7h-shifted call set, revert `_day_window`
     only — the display conversion stays correct either way.
  2. Legacy transcript-viewer rows show UTC times until re-backfilled.
