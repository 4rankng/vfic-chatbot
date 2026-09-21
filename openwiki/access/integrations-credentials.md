---
type: system
title: Admin-managed integration credentials (encryption at rest)
description: Where Zalo, MiniMax, OpenRouter, custom OpenAI-compatible, and Facebook Messenger credentials are stored, how AES-GCM + AAD context binding protects them, and how the graph layer resolves them per turn.
tags: [credentials, encryption, aes-gcm, integrations, zalo, minimax, openrouter, custom-llm, facebook-messenger]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
sources:
  - id: openwiki-source-b9104c053ff9989fbde4d8c7
    resource: repo://backend/app/api/integrations.py
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
  - id: openwiki-source-5fb38a533b77ac01c110f5ae
    resource: repo://backend/app/core/preamble_cache.py
  - id: openwiki-source-7767c87e565ad5a9eda80990
    resource: repo://backend/app/graph/factories.py
  - id: openwiki-source-a48516f3855d6f7289617339
    resource: repo://backend/app/models/integration.py
  - id: openwiki-source-085098b884681cab422762c1
    resource: repo://backend/app/services/integration_settings.py
generated: { by: "opencode", at: "2026-09-21T02:42:43.794Z" }
---

Admin-managed credentials are the runtime seam between the recruiter console
and every external service the bot depends on — the Zalo Bot Platform, the
Zalo Official Account API, the MiniMax language model, the OpenRouter
language model, an operator-supplied OpenAI-compatible failover, and the
Meta/Facebook Messenger Graph API. All long-lived secrets flow through one
persistence layer (`IntegrationSetting`) and one resolution service
(`IntegrationSettingsService`); everything else in the codebase only ever
sees resolved runtime configs that contain decrypted plaintext, never the
storage row.

## Storage model

The `integration_settings` table is keyed by `key` (a stable string
identifier such as `zalo_bot_token`, `minimax_api_key`, or
`facebook_page_token:<page_id>`) and stores `encrypted_value` plus an
`is_secret` boolean and an `updated_by` user id. The model is owned by
`backend/app/models/integration.py:IntegrationSetting`. Per-Page Facebook
tokens are dynamic — they are keyed by `facebook_page_token:<page_id>` so
the Page id is recoverable from the row itself. Provider-test results
(`minimax_last_test`, `openrouter_last_test`, `custom_llm_last_test`) live
in the same table as plaintext JSON — they are probe artifacts, not
configuration.

## Encryption envelope

`IntegrationSettingsCipher` (in `backend/app/services/integration_settings.py`)
wraps every secret in **AES-GCM with a 12-byte random nonce** and stores the
result as `v1:<base64(nonce||ciphertext)>`.

- The key is `SHA-256(integration_settings_encryption_key or jwt_secret)`.
  The cipher itself does not consult `app_env`; the dev fallback is gated
  by `Settings.model_post_init`, which refuses to boot production with an
  empty `integration_settings_encryption_key`, and refuses to boot with
  the dev default `jwt_secret` unless `app_env == "development"`
  (`backend/app/core/config.py:438`).
- Decrypt failures (wrong key after rotation, corrupt row) are caught with
  `InvalidTag` and logged with the key name only — never the ciphertext
  or plaintext — and the row is skipped so callers fall back to
  `Settings` env vars rather than 500ing the admin view.

### Context-bound envelopes for per-Page tokens

Per-Page Facebook tokens use `v2:` rows. The Page id is encoded as the AEAD
**associated data (AAD)**, so a ciphertext produced for Page `A` fails to
decrypt under Page `B` (`InvalidTag` from GCM). This blocks the attack where
a row with valid ciphertext is moved between Pages: the GCM tag fails
before the message is ever released. The methods
`encrypt_with_context` / `decrypt_with_context` live next to the legacy
`v1:` pair.

Two paths consume the v2 envelope:

- `decrypt_with_context(stored, context)` is the general helper. A non-`v2:`
  input falls back to the legacy `decrypt` so older rows keep working for
  callers that do not need AAD binding.
- `_stored_value_with_context` is the Page-token path inside
  `resolve_facebook(page_id)`. It **rejects** legacy `v1:` rows outright
  (`logger.warning("facebook page token rejected (not context-bound) ...")`
  and returns empty) so the context binding is enforced at runtime, not
  just at write time. Wrong-context decryptions surface as
  "reconnect required" rather than releasing a swapped token.

## What is encrypted vs. what is plaintext

| Field | Stored as | Why |
|---|---|---|
| `zalo_bot_token`, `zalo_bot_webhook_secret`, `zalo_oa_secret_key`, `zalo_oa_access_token`, `zalo_oa_refresh_token` | `v1:` ciphertext | Provider-issued secrets |
| `zalo_oa_app_id` | plaintext (nullable) | Appears in OAuth URLs in the browser; not sensitive |
| `minimax_api_key`, `openrouter_api_key`, `custom_llm_api_key` | `v1:` ciphertext | Provider API keys |
| `minimax_enable`, `openrouter_enable`, `custom_llm_enable`, `llm_default_provider`, `llm_failover_order`, `*_model` | plaintext | Feature flags / non-sensitive model names |
| `*_last_test` | plaintext JSON | Probe artifact, not configuration |
| `facebook_app_id`, `facebook_login_config_id` | plaintext | Browser OAuth URL parameters |
| `facebook_app_secret`, `facebook_webhook_verify_token` | `v1:` ciphertext | Meta App secrets |
| `facebook_page_token:<page_id>` | `v2:` ciphertext, AAD = page_id | Page-scoped, context-bound |

## Admin view never returns the secret

The per-provider admin views (`admin_view`, `admin_minimax_view`,
`admin_openrouter_view`, `admin_custom_llm_view`,
`admin_facebook_oauth_view`) return only `{configured: bool, preview:
'<first4>...<last4>'}` for each secret. The `_preview` helper masks short
values entirely with `*` so an empty token or a token shorter than 8
characters is fully redacted. All admin endpoints are gated by
`require_admin`. Non-secret fields (app ids, model names, base URLs, the
enabled flag, the failover ranking) are surfaced verbatim.

## LLM provider tier

Four providers compete for one active slot per turn. `_SELECTABLE_PROVIDERS`
is `{minimax, openrouter, custom}`; `_CANONICAL_PROVIDER_ORDER` is
`(minimax, openrouter, custom)`. An unrecognised stored value falls back
to `minimax` rather than leaving the process with no provider.

- **Active provider** is `llm_default_provider` (DB-stored, env fallback).
- **Failover ranking** is `llm_failover_order` (CSV, operator-ranked spare
  order). `normalize_llm_failover_order` parses it into a full canonical
  permutation: unknown or stale names are dropped, duplicates collapse to
  their first occurrence, unranked providers trail in canonical order.
  The default chain mirrors the historic order — the other first-class
  provider, then the OpenAI-compatible slot — but a partial operator
  order only moves the providers they actually ranked.

The active + ranked failover set drives `_build_failover_chain`: each
enabled, non-active provider with usable credentials joins the chain in
rank order. Build failures are swallowed per-provider — a misconfigured
spare must not take down the turn.

### Custom LLM provider

`resolve_custom_llm()` builds a `CustomLlmRuntimeConfig` from
`CUSTOM_LLM_SETTING_KEYS` (DB-first, env fallback). The `usable` property
is `enabled and api_key and base_url and agent_model` — `safety_model`
and `fast_model` mirror `agent_model` unconditionally so a stray stored
or env value (e.g. a browser autofill of an email into a model box) can
never reach a request. The label defaults to *Dự phòng* so the
failover board stays readable when the operator does not set one.

### Custom LLM real probe

`record_provider_test_result` persists one real-probe outcome per
provider (`minimax_last_test`, `openrouter_last_test`,
`custom_llm_last_test`) so the settings page can render
"tested 2 minutes ago · 412 ms" across reloads. Both pass and fail are
persisted (a dead provider must keep showing its error). The probe runs
ONE real chat completion via `probe_openai_compatible_chat`, replacing
the old key-presence checks: "configured" and "actually works" become
distinct facts. The custom-llm test endpoint also accepts operator-typed
credentials in the body so values can be validated BEFORE being saved.

## Resolution path

Every chatbot turn builds the full `GraphDeps` via
`graph.factories.build_deps(db)` (`backend/app/graph/factories.py:760`).
The expensive LLM clients + embedder are cached process-wide (see
"Caching" below); `build_deps` re-binds only the per-turn pieces. Within
that flow:

- `integration_settings.resolve_zalo()` is called **per turn** (cheap —
  Redis-cached via `cached_zalo_config`) so a rotated OA token takes
  effect on the very next turn without invalidating the expensive LLM
  client cache.
- `resolve_minimax()`, `resolve_openrouter()`, and `resolve_custom_llm()`
  are resolved inside `_build_cached_clients`, which runs only when the
  LLM-cache key (mm + or + fb namespace versions) flips.
- `resolve_facebook(page_id)` is called **per Page** by the channel-adapter
  layer, not per turn. A turn scoped to a Facebook Page resolves the
  Page-specific runtime; a Zalo turn does not.

```text
graph.build_deps(db)
  ├─> _build_cached_clients(db)
  │     └─> resolve_minimax / resolve_openrouter / resolve_custom_llm
  │           cache key = mm:<v> | or:<v> | fb:<v>
  │     └─> _build_failover_chain(order=resolve_llm_failover_order())
  └─> resolve_zalo() ─ per-turn, cheap
        └─> cached_zalo_config(_load)   # process-local LRU, 5-min TTL
              └─> _load: SELECT IntegrationSetting WHERE key IN (ZALO_SETTING_KEYS)
                    └─> cipher.decrypt(row.encrypted_value)
                          fallback: Settings.<env_var>  when DB row missing
```

Each namespace has its own `cache_version` counter (`integration_zalo`,
`integration_minimax`, `integration_openrouter`, `integration_facebook`,
`integration_custom_llm`) flipped on admin write via `bump_cache_version`,
so a credential rotation takes effect on the very next consumer without
invalidating unrelated namespaces.

### Zalo OA refresh flow

`refresh_oa_access_token()` is wired into `ZaloChannelSender` as a closure
(`refresh=lambda: integration_settings.refresh_oa_access_token()`) so when
an outbound send reports the access token invalid, the sender calls the
closure to fetch a fresh pair via the OA grant endpoint, persists both
tokens through `_write_secret`, and bumps the `integration_zalo` cache
version. A Redis `SET NX EX` lock (`zalo:oa:token:refresh`, 30s TTL)
prevents RQ workers from refreshing in parallel; losers re-read whatever
token the winner just stored.

The transport uses a dedicated `zalo_oa_token` HTTP client (separate from
the runtime OA sender because the token endpoint lives on a different
host — `oauth.zaloapp.com` vs `openapi.zalo.me` — and uses a different
auth shape — `secret_key` header, not `access_token`). Persistence order
is intentional: rotated pair committed before audit and cache-version
bump, so losing the new single-use refresh token to an audit failure
would force manual re-authorization.

## Caching

`backend/app/core/preamble_cache.py` defines the cache helpers. The rule
for secret-bearing caches is strict:

- **Process-local only.** Secret values live in `_LOCAL_SECRET_CACHE` keyed
  by `namespace + version + key_prefix` (LRU, capped at 16 entries per
  process). They never enter Redis — Redis is used exclusively for the
  namespace-version counter.
- **Version-bump invalidation.** Admin writes call `bump_cache_version`
  to flip the namespace counter, so the next read misses and re-decrypts.
- **Failure-isolated.** Any Redis version-read error bypasses the local
  cache and invokes the loader directly. Stale decrypted secrets are
  never served as a fallback when the version source is unreachable.
- **Cross-namespace flip on `llm_default_provider`.** When the active
  provider selector is part of a save, every provider snapshot must be
  invalidated — not just the namespace the operator wrote into —
  otherwise the routing flip stays stale until the snapshot TTL expires,
  exactly during the quota emergency the flip is for.
  `_bump_provider_namespaces(primary, changed)` does this: if
  `LLM_DEFAULT_PROVIDER` is in `changed`, every cached snapshot
  (`integration_minimax`, `integration_openrouter`,
  `integration_custom_llm`) is evicted and bumped; otherwise only the
  primary namespace is touched.

### LLM-client cache key

`_build_cached_clients` (in `backend/app/graph/factories.py:627`) keys
the process-wide LLM bundle by **all three** provider namespace versions
— `mm:<v> | or:<v> | fb:<v>` — covering `integration_minimax`,
`integration_openrouter`, and `integration_custom_llm`. Zalo config is
deliberately excluded from the key: Zalo feeds only the per-turn
`ZaloChannelSender`, so an OA token refresh must NOT invalidate the
expensive LLM clients. When a key flip happens, displaced bundles are
scheduled for retirement (a 600s grace window) so any in-flight turn
that already captured a reference can finish, then their underlying
HTTP pools are closed.

## Write path

Per-provider write methods (`update_zalo`, `update_minimax`,
`update_openrouter`, `update_custom_llm`, `update_facebook_oauth`) all
follow the same shape: encrypt non-empty values via `cipher.encrypt`,
upsert the `IntegrationSetting` row keyed by `key`, record an audit row
listing the changed keys (never the values), commit, and bump the
namespace versions so subsequent reads decrypt fresh. The `custom_llm`
panel also accepts `llm_failover_order` as a JSON list which is
serialised to CSV before storage; the `minimax` and `custom_llm` panels
both invalidate each other's snapshots when `llm_default_provider` is
the changed key.

Facebook Page access tokens take a different path:
`stage_facebook_page_token_upsert(page_id, token, updated_by)` writes the
pre-sealed `v2:` ciphertext directly (NOT via `_write_setting`, which
would double-encrypt) inside a `pg.insert(...).on_conflict_do_update`
statement. The caller owns commit/rollback so this can compose with
other writes inside a single transaction. After commit,
`set_facebook_page_token` calls `invalidate_facebook_cache` to evict
the local Facebook namespace and bump the version.

### Zalo webhook re-sync on save

Saving `zalo_bot_token` or `zalo_bot_webhook_secret` calls
`_sync_bot_webhook(settings_service, changed)`, which pushes the
just-saved secret to Zalo via `setWebhook`. Saving alone updates only
the app side; a mismatch silently 401-drops every inbound. The re-sync
only fires when the bot token or webhook secret was just changed
(avoids needless Zalo traffic on every save), and it is best-effort: a
failure is surfaced as a status flag on the response and never raises
because the DB save has already committed.

## What the rest of the codebase sees

Downstream callers receive frozen dataclasses:

- `ZaloRuntimeConfig` — bot token, bot webhook secret, OA app id, OA
  secret key, OA access token, OA refresh token, plus the constant
  `ZALO_BOT_API_BASE` / `ZALO_OA_API_BASE` from
  `backend/app/core/config.py`.
- `MinimaxRuntimeConfig` — api key, base url, agent / safety model
  names, the enabled flag, and the `default_provider` selector.
- `OpenRouterRuntimeConfig` — api key, base url, agent / safety /
  digest / embedding model names, embedding dim, the enabled flag, and
  the `default_provider` selector.
- `CustomLlmRuntimeConfig` — api key, base url, agent model (mirrored
  into safety + fast), label, enabled flag, and the
  `default_provider` selector. Carries a `usable` property that gates
  whether the provider can serve a turn.
- `FacebookRuntimeConfig` — bound to a single Page (app id, app secret,
  page id, decrypted page access token, verify token, Graph API version
  and base url). The Page access token is server-only and never
  serialised into API responses, logs, or queue payloads.
- `FacebookOAuthConfig` — the app-level Meta credentials used to drive
  OAuth + webhook verification. NOT bound to a specific Page; describes
  the Meta App itself.

These configs flow into:

- `graph.factories.build_deps` — wires `ZaloChannelSender` per turn,
  builds the cached LLM client bundle, scopes retrieval to the
  conversation's Page Projects when relevant.
- `graph.factories._build_failover_chain` — builds the cross-provider
  failover chain in operator-ranked order.
- `services.zalo_bot_service.ZaloBotAdminClient` — used by the admin
  probe endpoints.
- `services.zalo_oa_service.ZaloOASender` — used for outbound OA sends
  and for the profile-enrichment path that backfills OA user
  names/avatars.

## Caveats

- `INTEGRATION_SETTINGS_ENCRYPTION_KEY` rotation is not handled
  in-process; decrypting a row under the new key returns `InvalidTag` and
  the service logs a warning, falling back to env vars. Plan rotations
  with a maintenance window that re-writes the affected rows through the
  admin API.
- `v1:` rows (legacy, no AAD binding) decrypt unchanged via the general
  helper. Per-Page tokens are written through `encrypt_with_context` so
  they ship as `v2:`, and the per-Page resolution path rejects `v1:`
  rows outright.
- The dev fallback key (`JWT_SECRET`) is intentionally forgeable in
  dev. `Settings.model_post_init` refuses to boot production with the
  dev default so a deployed instance cannot accidentally sign admin JWTs
  or decrypt production secrets with a public key.
- Failover chain is gated on the operator actually enabling a spare
  provider with usable credentials. Enabling OpenRouter alongside
  MiniMax is enough to survive a spent MiniMax plan; an OpenRouter-only
  configuration has no failover unless the operator also enables the
  custom slot.
