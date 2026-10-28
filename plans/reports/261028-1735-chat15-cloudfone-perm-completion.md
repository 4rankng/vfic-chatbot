# Agent Completion Checklist

Copy this file to
`plans/reports/<YYMMDD-HHmm>-<slug>-completion.md` for each implementation task.
Replace every `PENDING` with `PASS`, `N/A`, or `BLOCKED`. A task is not complete
while any item is `PENDING` or `BLOCKED`.

Restored 2026-09-27 (DOC-19) after `65069078` deleted it. The 2026-09-27 sweep
had to reconstruct these sixteen gates from the previous sweep's report because
this file was gone; the gate list is meant to live here, not in the most recent
report. Do not renumber or drop gates when filling one in — a report that omits a
gate is a report that was not filled from this file.

## Task record

- Task: CHAT-15 (id 621) — tách quyền Cloudfone: mọi user xem Bản ghi cuộc gọi + transcript; chỉ Admin set up/cấu hình (API key/credentials, đồng bộ, mapping). Kèm UI/UX cho role tuyển dụng mở Cloudfone; timestamps hiển thị ICT (GMT+7).
- Scope: backend permission split (records endpoints → `get_current_user`, config endpoints giữ `require_admin`) + frontend trang "Bản ghi cuộc gọi" cho mọi role (nav + route, không exit về config) + tests + hợp đồng API doc.
- Files changed: `backend/app/api/integrations.py`, `backend/app/schemas/integrations.py`, `backend/tests/test_cloudfone_transcripts_api.py`, `backend/tests/test_cloudfone_admin_guard.py` (new); `frontend/src/components/atomic-crm/integrations/CallRecordsPage.tsx` (new), `frontend/src/components/atomic-crm/integrations/CallRecordsPage.test.tsx` (new), `frontend/src/components/atomic-crm/integrations/CloudfoneTranscriptsSection.tsx`, `frontend/src/components/atomic-crm/capabilities/kernel/{components.tsx,index.tsx,index.test.ts,mobile-overflow-navigation.test.tsx}`, `frontend/src/components/atomic-crm/capabilities/static-recruitment-runtime.ts`, `frontend/registry.json` (generated), `docs/architecture/api.md`, `plans/reports/261028-1735-chat15-cloudfone-perm-completion.md`.
- Instructions retrieved: ticket CHAT-15 full description qua tingting-plan MCP (`get_issue 621`); AGENTS.md (auto-loaded); audit code `backend/app/api/integrations.py`, `frontend/src/components/atomic-crm/integrations/*`, `capabilities/kernel/*`, `static-recruitment-runtime.ts`, `vietnamTime.ts`.
- Approval required: commit/push — được ủy quyền trong yêu cầu công việc; deploy — không yêu cầu (không thực hiện).
- Approval evidence: yêu cầu công việc trong phiên ("Commit + push code thật lên branch… KHÔNG deploy. Không Telegram.").

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | AC1–4 pinned by tests: non-admin xem/sọc/lọc transcript — `backend` 97 pass (toàn bộ suite transcripts chạy principal recruiter), frontend `CallRecordsPage.test.tsx` render bản ghi + giờ ICT "01/10/2026 17:02"; AC2 không có nút/tab Cài đặt — page test assert không có "Quay lại cài đặt Cloudfone", nav test assert recruiter không thấy "Cài đặt", deep-link `/settings` vẫn vào console wall chặn sẵn; AC3 config API 403 non-admin — `test_cloudfone_admin_guard.py` (GET/PUT settings + test connection = 403 recruiter); AC4 admin bình thường — cùng file: full save → 200 enabled/masked key, probe fail-fast missing list. |
| Diff is limited to the approved scope | PASS | `git log --stat` hai commit chỉ chứa Cloudfone permission split + nav/route/tests/docs liên quan; không chạm behavior ngoài ticket. |
| Protected operations were avoided or approved | PASS | Không deploy/merge/PR/branch mới; push đúng branch `fix-chat15-cloudfone-perm` theo yêu cầu; không gửi Telegram. |
| Focused tests/checks pass | PASS | Backend: `pytest tests/test_cloudfone_admin_guard.py tests/test_cloudfone_transcripts_api.py tests/test_cloudfone_settings.py tests/test_cloudfone_transcript_backfill.py tests/test_cloudfone_service.py tests/test_integrations_api.py` → 97 passed. Frontend: `vitest --project app` trên integrations + capabilities/kernel + layout → 19 files / 161 passed; thêm `mobile-containment.test.tsx` + `wcag-contrast.test.tsx` → 22 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest tests/test_architecture_boundaries.py` → 21 passed (import contract); toàn bộ vitest scope kernel/layout/integrations green — nav model, workspace shell, settings console navigation giữ nguyên behavior admin. |
| Lint passes for affected code | PASS | `ruff check` trên 4 file backend thay đổi → "All checks passed!"; `eslint --no-warn-ignored` trên 8 file frontend thay đổi → clean. |
| Type checking passes for affected code | PASS | `npm run typecheck` (`tsc --noEmit --project tsconfig.app.json`) → clean. |
| Build/import validation passes for affected code | PASS | Vitest browser lane load lazy chunk `CallRecordsPage` thành công (2 tests render qua route page); pre-commit `registry:gen` ghi nhận component mới vào `frontend/registry.json`; tsc validate toàn bộ import mới. |
| Security and privacy impact reviewed | PASS | Config (credentials, sync setup, test probe) giữ `require_admin` (403 với recruiter — test pin). Records endpoints mở cho `get_current_user` (bắt buộc đăng nhập, không anonymous); `Cache-Control: no-store` giữ nguyên cho PII transcript; settings view vẫn mask key (status-only). Backfill không lộ credentials — chỉ fetch dữ liệu mà viewer được xem. |
| Performance and async-I/O impact reviewed | PASS | Không thêm đường I/O mới; backfill có sẵn (auto-fetch mỗi ngày xem một lần, cap `MAX_TRANSCRIPTIONS_PER_DAY`); viewer vẫn lazy chunk — không kéo vào eager kernel graph (index.test.ts pin). |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Trang mới dùng lại kit `PageShell`/`PageHeading` + viewer cũ (wcag-contrast.test 22 pass không đổi); copy dùng lại `SETTINGS_VIEW_COPY` ("Cloudfone · Bản ghi cuộc gọi"); timestamps hiển thị ICT GMT+7 qua hợp đồng `vietnamTime`/formatters của viewer — pin "01/10/2026 17:02". |
| Error handling and compatibility reviewed | PASS | Deep-link `/settings` với non-admin vẫn bị chặn bởi console wall (behavior có sẵn, không đổi); `onBack` optional giữ nguyên flow admin console (`SettingsConsolePage.navigation.test` green); unknown call id vẫn 404 tiếng Việt (test pin). |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `docs/architecture/api.md` row `integrations` cập nhật hợp đồng auth (settings `require_admin`; Cloudfone transcripts JWT — CHAT-15). `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve." |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -rn "TODO\|FIXME\|HACK"` trên các file mới → 0. |
| Final `git diff --check` passes | PASS | `git diff --check` + `git diff --cached --check` → clean. |
| Final `git status --short` reviewed | PASS | Chỉ còn `docs/architecture/api.md` (contract update) + `frontend/registry.json` (generated) + report này — đều nằm trong commit cuối; không còn file lạ. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: backfill theo thiết kế mở cho mọi user đã đăng nhập (phục vụ "xem transcript bình thường" ở ngày chưa đồng bộ) — điểm gọi vendor + STT là cost surface, đã bị cap theo ngày. QA nên kiểm chứng bằng login 2 role thật như ticket yêu cầu ("login 2 role thử"): recruiter thấy menu "Bản ghi cuộc gọi", không thấy "Cài đặt", config API 403; admin setup bình thường.
