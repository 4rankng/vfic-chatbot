# Integration files sweep — ARCH-06 + ARCH-07

Lane: sweep-integrations. Date: 2026-09-24. Branch: main.

## Outcome

Both tickets landed. `services/integration_settings.py` (1,274 LOC) is now a
package (`cipher / storage / providers/{zalo,llm,facebook} / service` facade)
with every method AST-identical to its original. `api/integrations.py`
(1,363 LOC) is transport-only: the Zalo diagnostics (including the raw OA
OAuth POST), the LLM provider probes, and the whole Facebook OAuth flow moved
into `services/integrations/{zalo_diagnostics,llm_diagnostics,
facebook_oauth_flow}.py`. The router keeps every route handler name (route
inventory digest unchanged) and now parses the request, calls the service,
maps the domain error, and returns the response model. All 31 routes and the
public import surface (`from app.services.integration_settings import X`,
`from app.api.integrations import router`) are unchanged.

One process incident to flag: the graph lane's commit `c097cb46` ("refactor(graph):
remove the unreachable template fast lane") swept my entire ARCH-06 split
into their commit while it sat in my working tree/index — their commit
carries ~1,600 insertions of my package split under a message that only
describes the fast-lane removal. I verified `git diff HEAD` for the package
is zero lines against my version and the affected tests pass at that commit;
the code is intact, only the commit attribution is wrong. I did not rewrite
their commit (no history surgery on the shared tree). ARCH-07 has its own
clean commit: `e965aa66`.

## ARCH-06 — integration_settings split

Landed in `c097cb46` (content mine; see incident above).

New shape, mirroring the `services/conversation` facade + mixin pattern from
today's earlier splits:

- `app/services/integration_settings/__init__.py` — re-exports the complete
  old module surface (every constant, dataclass, cipher, service), so the 29
  importers of `IntegrationSettingsService` (api/integrations, graph/factories,
  workers, installation/repository, channels providers, outbox, etc.) needed
  zero import changes.
- `cipher.py` — `IntegrationSettingsCipher` byte-identical (AES-GCM,
  `v1:`/`v2:` versioning, AEAD context binding, the OPS-03/SEC-08 migration
  hazard docstring).
- `storage.py` — `StorageMixin`: `_stored_values`, `_write_setting`,
  `_stored_value_with_context`, `record/get_provider_test_result`,
  `_bump_provider_namespaces` (the shared `llm_default_provider` fan-out
  invalidation), `PROVIDER_TEST_KEYS`.
- `providers/zalo.py` — `ZaloSettingsMixin` + keys + `ZaloRuntimeConfig` +
  the OA refresh lock helpers: `resolve_zalo`, `admin_view`, `_write_secret`,
  `update_zalo`, `refresh_oa_access_token` (Redis SET NX EX + Lua CAS
  release, REL-03).
- `providers/llm.py` — `LlmSettingsMixin`: minimax / openrouter / custom /
  jev resolve+admin+update pairs, `resolve_llm_failover_order` (kept the
  subscript-with-membership read so the runtime-surface oracle still sees it
  the same way).
- `providers/facebook.py` — `FacebookSettingsMixin`: app-level credentials,
  step-up reveal (SEC-07), page-id-bound token upsert/delete staging.
- `service.py` — `IntegrationSettingsService(Storage, Zalo, Llm, Facebook)`
  facade with the original constructor verbatim.

Verification: 46/46 methods AST-identical to
`HEAD~:backend/app/services/integration_settings.py` (verified by script:
45 moved methods + the facade `__init__`). Test retargets were mechanical:
string patches `"app.services.integration_settings.record_audit"` → the
provider module each code path runs through (zalo ×5, llm ×5, facebook ×3,
one in test_facebook_oauth), `bump_cache_version` → zalo, one
`cached_jev_config` patch in test_graph_decisions → llm. That last file is
shared with the graph lane, so I staged only my hunk via
`git apply --cached` of a hand-built patch.

Crypto preservation evidence: cipher methods moved byte-identical (AST dump
equality); explicit post-move round-trip check passed — `v1:` seal/open
round-trip, `v2:` context-bound round-trip for the right page_id, and a wrong
page_id raises `InvalidTag`. No re-keying, no format change: existing stored
ciphertext decrypts exactly as before. Nothing logs credential material; the
key-name-only warning in `_stored_values` moved with its code.

## ARCH-07 — api/integrations extraction

Landed in `e965aa66` (8 files, +1,027/−777).

- `app/services/integrations/zalo_diagnostics.py` — `_safe_probe_error`,
  `_bot_admin_client`, `sync_bot_webhook` (the setWebhook change-detection
  policy), `probe_zalo_bot_channel`, `probe_zalo_oa_channel` (the four-layer
  diagnostic).
- `app/services/integrations/llm_diagnostics.py` — `probe_and_record`
  (formerly `_probe_and_record`), `probe_minimax`, `probe_openrouter`,
  `probe_custom_llm`, `probe_jev`.
- `app/services/integrations/facebook_oauth_flow.py` — the Redis state/flow
  wiring (`facebook_oauth_coordinator`, `load_facebook_oauth_flow`),
  `start_oauth_flow`, `run_oauth_callback`, `list_oauth_pages`,
  `complete_page_selection` (subscribe + D1-gate unsubscribe compensation),
  `probe_facebook_connection`, `disconnect_page`.
- `app/api/integrations.py` — 31 routes, same names/paths/docstrings; bodies
  delegate. `_fb_frontend_redirect_url`, `_FB_REDIRECT_HEADERS`, and the
  assignment-CRUD mapping stayed in the router (they are the response
  mapping, which is the router's job per the ticket).

Wire-behavior preservation: every moved function body is AST-identical to
HEAD after applying only the five helper renames (`_sync_bot_webhook` →
`sync_bot_webhook`, `_fb_callback_url` → `facebook_callback_url`, etc.).
Two documented seams, nothing else:

1. `run_oauth_callback`: the seven `return _fb_oauth_redirect_error(...)` /
   `RedirectResponse(...)` statements became
   `FacebookOAuthCallbackOutcome(status=..., error=/flow_id=...)` records; the
   router maps them back through the same `_fb_frontend_redirect_url` + 302 +
   `Cache-Control: no-store` / `Referrer-Policy: no-referrer` headers, same
   query params in the same order. The raw OA OAuth POST moved verbatim —
   same URL, form-encoded body, conditional per-request `secret_key` header,
   process-scoped client name `zalo_oa_oauth_diag`, timeout 10 — so the wire
   shape is byte-identical.
2. `probe_facebook_connection`: one function-local
   `from app.services.integration_settings import IntegrationSettingsService`
   was hoisted to module level (it existed only so a string monkeypatch could
   intercept it); tests now patch the flow module directly.

No fastapi import exists anywhere under `services/` — the boundary held.

Test retargets (all in my ownership): test_integrations_api patches moved to
`zalo_diagnostics` (probes construct the settings service there; the PUT /zalo
tests keep patching the router's service for the handler while the bot client
patch moved), test_facebook_oauth `_redis`/`IntegrationSettingsService`/
`GoneError`/`UpstreamError`/`_fb_callback_url` patches moved to the flow
module (plus one local `flow` capsule variable renamed to `capsule` to unshadow
the module alias). Test intent unchanged everywhere.

## Runtime-surface inventory

Re-pinned in the same commits as the boundary moves, with ledger comments:

- ARCH-06: `provider_boundary` 119 → 111. The OA refresh transport (post +
  eval + surrounding reads) stayed reviewed inside `providers/zalo.py` (it
  still carries the `get_http_client` marker); the LLM/Facebook `._load`
  dict reads and storage `db.get` upserts landed in non-transport modules and
  left the snapshot — same pattern as the earlier clients.py split.
- ARCH-07: 111 → 79. The forced by-path scan rule moved from
  `api/integrations.py` to `services/integrations/zalo_diagnostics.py` so the
  raw OAuth POST (`probe_zalo_oa_channel post 1`) and the bot probe reads
  remain inventoried; the ~30 dropped rows were route-decorator artifacts of
  the old forced rule. Broad digest re-pinned both times (currently
  `6b353814…07b43`); route inventory digest unchanged (all handler names
  kept).

## Verification

- Narrow, per ticket: test_integration_settings (26), test_zalo_oa_token_refresh
  (6), test_llm_failover (12), test_facebook_oauth (58), test_integrations_api
  (22), test_zalo_oa_test_connection (5), test_graph_decisions (23),
  test_graph_factories, test_persistence_worker, test_knowledge_base_service,
  test_facebook_account_lifecycle, test_backfill_oa_profiles, test_outbox,
  integration-marked lifecycle/outbox files — all green.
- Full lane `pytest -m "not integration"`: **2261 passed, 24 skipped, 3
  failed + 1 uncollectable module — every failure attributed to other lanes'
  in-flight uncommitted work**: two frontend boundary edges (sweep-fe's
  uncommitted conversation/projects files) and `test_model_tiering::
  test_template_lane_is_fast_eligible` (stale after sweep-graph's committed
  fast-lane removal in c097cb46). `tests/test_project_knowledge_boundaries.py`
  cannot collect because sweep-services currently has
  `project_knowledge/application/{cache,categories,ingestion}.py` deleted in
  their working tree; it was excluded, not silently skipped.
- `ruff check` clean on all touched files; `python -c "import app.main"` and
  compileall pass.

## Protected paths / constraints

No protected path was edited. No graph/, services/conversation/,
services/installation/, services/retrieval/, core/config.py, frontend/,
Makefile, scripts/, .github/, compose, alembic/, docs/, or kanban/ file was
touched by me. No credentials or PII logged; no new dependencies; no
migration changes.

## Unresolved / for the lead

1. ARCH-06 attribution: content lives in the graph lane's `c097cb46`; if the
   kanban card needs a hash, cite that one with this caveat, or land a
   no-op-noting follow-up if you prefer a clean pointer.
2. `test_model_tiering::test_template_lane_is_fast_eligible` fails at HEAD
   from the graph lane's committed removal — someone should retarget it.
3. Remind lanes to run `git diff --cached --name-only` immediately before
   `git commit`; the shared-index incident was caused by the other direction
   of the check I was told to run.

Status: DONE_WITH_CONCERNS
Summary: ARCH-06 (settings package split, byte-identical, crypto semantics
preserved and proven) and ARCH-07 (router → transport-only, wire shapes
preserved, inventory re-pinned) are both landed and green; ARCH-06 rides
inside the graph lane's commit c097cb46 after an index sweep, ARCH-07 is
e965aa66.
Concerns: the mis-attributed ARCH-06 commit (content verified intact); the
full-lane run shows 3 failures + 1 blocked module, all attributed to other
lanes' in-flight work and listed above.
