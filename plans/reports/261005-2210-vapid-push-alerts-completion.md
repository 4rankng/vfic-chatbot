# Web Push alerts (VAPID) — completion record

## Task record

- Task: when the Zalo OA refresh token is rejected, or the chatbot fails to send the
  same reply twice, deliver an OS-level push notification to the operators — Web Push
  (VAPID), per the user's answer to the transport/trigger question (2026-10-05).
- Scope: backend (`pywebpush` dependency, VAPID settings, `push_subscriptions`
  model + migration `0068`, `services/push/*`, the two trigger sites, the
  `/api/v1/notifications` router, `scripts/generate_vapid_keys.py`,
  `scripts/prod-env.sh`, `backend/Makefile`), frontend (`public/push-sw.js`,
  `vite.config.ts` workbox injection, `atomic-crm/notifications/*`, the bell panel),
  docs (`docs/architecture/api.md`, `docs/ops/deployment-guide.md`,
  `backend/.env.example`), tests.
- Instructions retrieved: `AGENTS.md`, `docs/architecture/system-architecture.md`,
  `docs/development/code-standards.md`, `docs/development/testing.md`,
  `docs/ops/deployment-guide.md`, `standards/agent-completion-checklist.md`.
- Approval required: yes (new migration, new dependency, prod deploy).
- Approval evidence: user in-session — "if refresh token fail or chatbot fail to
  send message twice please send app push notification", then the mechanism choice
  "Web Push (VAPID) — full pipeline" with triggers "Refresh token rejected" +
  "Chatbot failed to send the same reply twice" (2026-10-05).

## What was added

| piece | why |
|---|---|
| `services/push/service.py` | Fan-out to every active admin's subscriptions, per-endpoint failure isolation, 404/410 pruning, Redis `SET NX EX` dedupe that fails open. `pywebpush` runs in a worker thread (`asyncio.to_thread`). |
| `push_subscriptions` (0068) | One row per browser: endpoint + p256dh/auth + `user_id`. Additive; `downgrade()` drops it. |
| `/api/v1/notifications` | `GET /vapid-public-key` (public half, `enabled` flag), `POST`/`DELETE /subscriptions` (upsert by endpoint, scoped to the caller), `POST /test` (503 without keys, 409 without a subscription). |
| `zalo.py::_alert_refresh_rejected` | Fires on Zalo's `-14014 Invalid refresh token` refusal, deduped per account for 6 h. This is the trigger production needed: 45 failed sends in 24 h, all OA `tingting`. |
| `reconcile_worker._alert_stuck_conversation` | Fires from the two branches added earlier: the retry cap tripping (`failed_send_exhausted`) and a dead-credential skip (`terminal_send`), deduped per conversation. |
| `public/push-sw.js` + `workbox.importScripts` | `push` + `notificationclick` handlers in the generated service worker; the notification's `url` focuses an existing tab or opens one. |
| `notifications/pushNotifications.ts`, `usePushNotifications.ts`, `PushNotificationsToggle.tsx` | Subscribe/unsubscribe/self-test in the bell panel with Vietnamese errors for every refusal path. |
| `scripts/generate_vapid_keys.py` + `prod-env.sh` + `Makefile` | The deploy generates and appends the pair when `.env` lacks it (verified against a pre-existing file with no keys); `make db` does the same locally. |

## Gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior complete | PASS | Both triggers push; a deployment without keys logs instead of failing; the toggle + self-test prove delivery from the console. |
| Diff limited to approved scope | PASS | Files listed above; the only unrelated edit is the deployment guide's Alembic HEAD line + env table, both required by the new migration. |
| Protected operations avoided or approved | PASS | Prod deploy was explicitly requested; the migration is additive and was walked up → down → up on the dev database. |
| Focused tests pass | PASS | `pytest tests/test_push_notifications.py tests/test_generate_vapid_keys.py tests/test_reconcile_worker.py tests/test_lead_extraction.py tests/test_backfill_explicit_candidate_names.py tests/test_runtime_surface_inventory.py tests/test_deployment_makefile.py tests/test_frontend_api_contract.py -q`. Frontend: `vitest --project app run src/components/atomic-crm/notifications` → 7 passed (subscribe, key rotation, denied permission, unsubscribe, self-test). |
| Lint passes | PASS | `ruff check app scripts tests` → "All checks passed!"; `npx eslint src/components/atomic-crm/notifications src/components/atomic-crm/layout/topbar` → clean. |
| Type checking passes | PASS | `npm run typecheck` → clean. |
| Build/import validation | PASS | `alembic upgrade head` created `push_subscriptions` (id, user_id, endpoint, p256dh, auth, user_agent, failure_count, created_at, last_seen_at); `alembic downgrade -1` dropped it; `upgrade head` recreated it. `pywebpush 2.5.0` added via `uv add`. |
| Security and privacy reviewed | PASS | Alert bodies carry a conversation/account label, never message content or phone numbers. Subscription rows are browser handles, deleted on 404/410 and on unsubscribe; the VAPID public key is public by design and the private half stays in `/opt/vfic/.env` (mode 0600, carried by the existing backup path). Only admins receive the two alerts. |
| Performance / async-I/O reviewed | PASS | One blocking push send per subscription per alert, off-loop; deduped for 6 h so a refresh attempted every turn cannot become a push per turn. Pruning keeps the fan-out bounded by real browsers. |
| Accessibility / Vietnamese UX | PASS | Toggle lives in the bell panel next to the question it answers; errors are Vietnamese `role="alert"` text; buttons use the Untitled UI controls already in that panel. |
| Error handling / compatibility | PASS | Every trigger is wrapped: a push or Redis failure never breaks the refresh path or a reconcile sweep. No VAPID keys → `push_enabled()` false → alerts log and the toggle hides. A rotated pair is repaired by re-creating the browser subscription. |
| Documentation impact | PASS | `docs/architecture/api.md` (notifications row, 13→14 route groups), `docs/ops/deployment-guide.md` (HEAD `0068`, Web Push env table), `backend/.env.example` (three variables). `node scripts/check-doc-links.mjs` unchanged paths. |
| No new unlinked TODO/FIXME/HACK | PASS | None. |
| `git diff --check` / `git status --short` | PASS | Clean at commit time. |

## Result

- Overall status: **PASS**.
- Notes / follow-ups:
  1. Push only reaches browsers that enabled it (bell → "Bật thông báo đẩy"). Until
     someone does, the two alerts remain log-only, which is the previous behaviour.
  2. The deploy appends the VAPID pair to `/opt/vfic/.env`; the containers must be
     recreated for it to take effect — the blue/green cutover does that, so no manual
     step is needed. Rotating the pair later invalidates stored subscriptions and
     requires re-enabling from the console.
  3. The 6 h dedupe windows are deliberate: a dead credential or a stuck thread stays
     broken until an operator acts, and the reconcile wedge runs every minute.
