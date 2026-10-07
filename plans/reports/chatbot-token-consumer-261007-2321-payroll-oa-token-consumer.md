# Chatbot consumes payroll-managed TingTing OA tokens — completion report

Agent: chatbot-token-consumer · 2026-10-08 · Repo: /Volumes/LexarSSD/projects/chatbot

## Outcome

The chatbot's `tingting` Zalo OA account now consumes payroll-managed access
tokens (push-receive + pull), and the admin-managed OA credentials are gone.
Four commits on `main`, not deployed (controller deploys after review).

## Commits

| Commit | Scope |
|---|---|
| `ac5d2fc6` | Push webhook `POST /webhooks/zalo-oa-token` (X-API-Key = `tingting_api_key`, 401/400/200, token never logged) + pull branch: `refresh_oa_access_token("tingting")` GETs `{tingting_api base}/api/v1/integration/zalo/token` instead of Zalo OAuth; no Redis lock (idempotent pull, documented); non-tingting accounts unchanged |
| `1fe672cf` | Admin OA credentials removed: `/tingting/oa/check` route deleted, Update schema 422s any `zalo_oa_*` field (`extra="forbid"`), Out schema replaces four credential statuses with `oa_token_updated_at` + fixed note "Payroll quản lý và tự gia hạn token Zalo OA"; `link()`/`unlink()`/probe machinery removed, `TingtingOaLinkService` keeps only the read side (`verified_oa_id` for routing + reset gate); stored token row left as the runtime AT |
| `28d49ee8` | Console: TingTing card drops the four credential inputs and the re-probe button, renders the ownership note + token last update (`formatVietnamDateTime`); save body carries only api_key/hotline/switch; `checkTingtingOa` gateway method removed |
| `18be06a2` | Boundary fix: `app.api` may not import `app.core` — the push write path (storage + audit + cache invalidation) moved into `IntegrationSettingsService.store_pushed_oa_token`; route is transport-only |

## Files

Backend: `app/api/webhooks.py`, `app/services/tingting_api.py` (`TINGTING_ZALO_TOKEN_PATH`,
`fetch_zalo_oa_access_token`), `app/services/integration_settings/providers/zalo.py`
(branch, `_pull_tingting_oa_token_from_payroll`, `_alert_payroll_token_unavailable`,
`store_pushed_oa_token`, `oa_account_token_updated_at`),
`providers/tingting.py`, `app/services/tingting_oa.py` (rewritten to the read side),
`app/schemas/integrations.py`, `app/api/integrations.py`.
Frontend: `integrations/TingtingSection.tsx`, `integrations/api.ts`,
`SettingsConsolePage.navigation.test.tsx`.
Tests: `test_webhooks.py` (push: 200 stores/401 key/400 body), `test_zalo_oa_token_refresh.py`
(pull stores+returns, payroll failure → None + deduped alert, non-tingting still Zalo OAuth,
push store writes+audits), `test_tingting_api.py` (pull success/no-key/503/no-token),
`test_tingting_oa_link.py` (rewritten to the read-side contract),
`test_integrations_api.py` (schema rejects `zalo_oa_*`), inventory gate updated.

## Verification

- Inventory deltas attributed with a HEAD-worktree `_runtime_calls`/route-scan
  diff before each bump: exactly +1 route (webhooks 4→5), then -1 route
  (integrations 39→38), +2 provider_boundary rows (`.get` reads in the two
  provider-transport files; no new egress site — the pull rides `_send`).
  Strict `runtime_surface_inventory.json` fixture unchanged (verified).
- `test_tingting_api.py`, `test_webhooks.py`, `test_runtime_surface_inventory.py`,
  `test_architecture_boundaries.py`, `test_zalo_oa_token_refresh.py`,
  `test_tingting_oa_link.py`, `test_integrations_api.py`,
  `test_tingting_oa_processing_switch.py`, `test_zalo_multi_oa.py`,
  `test_graph_factories.py`, `test_zalo_oa_channel_probe.py`,
  `test_zalo_oa_test_connection.py`, `test_integration_settings.py` — all pass
  with `-p no:randomly` at the final commit.
- `ruff check` clean on every touched backend file; frontend `npm run typecheck`
  clean; full frontend unit suite 1031/1032 (the 1 failure is a pre-existing
  PerformancePage matcher-timeout flake that passes in isolation, unrelated page).

## Item 4 (runtime call sites) — verified, no change needed

`graph/factories.py:425`, `workers/persistence_worker.py:150`,
`outbox/dispatcher.py:155` all pass `account_key` into
`refresh_oa_access_token`; the tingting branch lives inside that function, so
the default account keeps hitting the Zalo OAuth branch (pinned by test).

## Open items / concerns

1. Fresh-install provisioning gap (inherent to the owner's decision): with the
   link flow gone, a brand-new deployment has no `ChannelAccount` row for
   `tingting` (no discovered `oa_id` metadata), so inbound routing cannot
   identify the OA and the reset flow stays unbound until that row exists by
   other means. The deployed instance keeps its existing row, so prod is
   unaffected.
2. Stale stored `zalo_oa_app_id/secret_key/refresh_token:tingting` rows remain
   in the DB by instruction (next push/pull overwrites only the access token).
   If payroll ever wants them purged, that is a separate ops step.
3. First send after deploy may still fail once on the stale stored access
   token; the failure triggers the payroll pull and the account self-heals
   (or payroll's startup push lands first).
