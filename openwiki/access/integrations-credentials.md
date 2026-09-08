---
type: system
title: Admin-managed integration credentials (encryption at rest)
description: Where Zalo, MiniMax, OpenRouter and Facebook Messenger credentials are stored, how AES-GCM + AAD context binding protects them, and how the graph layer resolves them per turn.
tags: [credentials, encryption, aes-gcm, integrations, zalo, minimax, openrouter, facebook-messenger]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
---

Admin-managed credentials are the runtime seam between the recruiter console
and every external service the bot depends on — the Zalo Bot Platform, the
Zalo Official Account API, the MiniMax language model, the OpenRouter language
model, and the Meta/Facebook Messenger Graph API. All long-lived secrets flow
through one persistence layer (`IntegrationSetting`) and one resolution
service (`IntegrationSettingsService`); everything else in the codebase only
ever sees resolved runtime configs that contain decrypted plaintext, never the
storage row.

## Storage model

The `integration_settings` table is keyed by `key` (a stable string
identifier such as `zalo_bot_token`, `minimax_api_key`, or
`facebook_page_token:<page_id>`) and stores `encrypted_value` plus an
`is_secret` boolean and an `updated_by` user id. The model is owned by
`backend/app/models/integration.py:IntegrationSetting`. Per-Page Facebook
tokens are dynamic — they are keyed by `facebook_page_token:<page_id>` so the
Page id is recoverable from the row itself.

## Encryption envelope

`IntegrationSettingsCipher` (in `backend/app/services/integration_settings.py`)
wraps every secret in **AES-GCM with a 12-byte random nonce** and stores the
result as `v1:<base64(nonce||ciphertext)>`.

- The key is `SHA-256(INTEGRATION_SETTINGS_ENCRYPTION_KEY)` (the env value,
  never the committed default). In `app_env == development` it falls back to
  `SHA-256(JWT_SECRET)` so local setup stays light.
- `Settings.model_post_init` refuses to boot when `app_env != "development"`
  and `integration_settings_encryption_key` is empty — production must never
  re-use the dev fallback. (`backend/app/core/config.py:413`)
- Decrypt failures (wrong key after rotation, corrupt row) are caught with
  `InvalidTag` and logged with the key name only — never the ciphertext or
  plaintext — and the row is skipped so callers fall back to `Settings` env
  vars rather than 500ing the admin view.

### Context-bound envelopes for per-Page tokens

Per-Page Facebook tokens use `v2:` rows. The Page id is encoded as the AEAD
**associated data (AAD)**, so a ciphertext produced for Page `A` fails to
decrypt under Page `B` (`InvalidTag` from GCM). This blocks the attack where a
row with valid ciphertext is moved between Pages: the GCM tag fails before
the message is ever released. The methods
`encrypt_with_context` / `decrypt_with_context` live next to the legacy
`v1:` pair and the legacy path is kept as a fallback for any unconverted
row.

## What is encrypted vs. what is plaintext

| Field | Stored as | Why |
|---|---|---|
| `zalo_bot_token`, `zalo_bot_webhook_secret`, `zalo_oa_secret_key`, `zalo_oa_access_token`, `zalo_oa_refresh_token` | `v1:` ciphertext | Provider-issued secrets |
| `zalo_oa_app_id` | plaintext (nullable) | Appears in OAuth URLs in the browser; not sensitive |
| `minimax_api_key`, `openrouter_api_key` | `v1:` ciphertext | Provider API keys |
| `minimax_enable`, `openrouter_enable`, `llm_default_provider`, `*_model` | plaintext | Feature flags / non-sensitive model names |
| `facebook_app_id`, `facebook_login_config_id` | plaintext | Browser OAuth URL parameters |
| `facebook_app_secret`, `facebook_webhook_verify_token` | `v1:` ciphertext | Meta App secrets |
| `facebook_page_token:<page_id>` | `v2:` ciphertext, AAD = page_id | Page-scoped, context-bound |

## Admin view never returns the secret

`IntegrationSettingsService.admin_view()` (and the per-provider view methods)
return only `{configured: bool, preview: '<first4>...<last4>'}` for each
secret. The `_preview` helper masks short values entirely with `*` so an
empty token or a token shorter than 8 characters is fully redacted. The admin
API (`backend/app/api/integrations.py`) is gated by `require_admin`.

## Resolution path

Every chatbot turn asks `IntegrationSettingsService` for a fresh
`ZaloRuntimeConfig`, `MinimaxRuntimeConfig`, `OpenRouterRuntimeConfig`, or
`FacebookRuntimeConfig`. The service is constructed once per turn inside
`graph.factories.build_deps` (`backend/app/graph/factories.py:617`):

```text
graph.build_deps(db)
  └─> IntegrationSettingsService(db).resolve_zalo()
        └─> cached_zalo_config(_load)   # process-local LRU, 5-min TTL
              └─> _load: SELECT IntegrationSetting WHERE key IN (ZALO_SETTING_KEYS)
                    └─> cipher.decrypt(row.encrypted_value)
                          fallback: Settings.<env_var>  when DB row missing
```

The same pattern applies to `resolve_minimax()` and `resolve_openrouter()`.
Each namespace has its own `cache_version` counter (`integration_zalo`,
`integration_minimax`, `integration_openrouter`, `integration_facebook`)
flipped on admin write via `bump_cache_version`, so a credential rotation
takes effect on the very next turn without invalidating the expensive LLM
client cache (see "Caching" below).

### Zalo OA refresh flow

`refresh_oa_access_token()` is wired into `ZaloChannelSender` as a closure
(`refresh=lambda: integration_settings.refresh_oa_access_token()`) so when an
outbound send reports the access token invalid, the sender calls the closure
to fetch a fresh pair via the OA grant endpoint, persists both tokens
through `_write_secret`, and bumps the `integration_zalo` cache version. A
Redis `SET NX EX` lock prevents RQ workers from refreshing in parallel; losers
re-read whatever token the winner just stored.

## Caching

`backend/app/core/preamble_cache.py` defines the cache helpers. The rule for
secret-bearing caches is strict:

- **Process-local only.** Secret values live in `_LOCAL_SECRET_CACHE` keyed by
  `namespace + version + key_prefix`. They never enter Redis — Redis is used
  exclusively for the namespace-version counter.
- **Version-bump invalidation.** Admin writes call `bump_cache_version` to
  flip the namespace counter, so the next read misses and re-decrypts.
- **Failure-isolated.** Any Redis version-read error bypasses the local cache
  and invokes the loader directly. Stale decrypted secrets are never served
  as a fallback when the version source is unreachable.
- **Scoped to the namespace that drives the consumer.** `_build_cached_clients`
  keys the LLM-client cache only by the `integration_minimax` and
  `integration_openrouter` versions, deliberately excluding Zalo. A Zalo
  token rotation therefore rebuilds the per-turn Zalo sender on the next
  turn instead of tearing down the cached LLM clients.

## Write path

`IntegrationSettingsService.update_zalo(...)` (and the equivalent methods for
each provider) is called from the admin API. The service:

1. Encrypts each non-empty value via `cipher.encrypt`.
2. Upserts the `IntegrationSetting` row keyed by `key`.
3. Records an `audit` row tagged `update_zalo_integration_settings` listing the
   changed keys (never the values).
4. Commits, calls `evict_local_namespace(NS_INTEGRATION_ZALO)`, and bumps
   the cache version so subsequent reads decrypt fresh.

Facebook OAuth refresh follows the same write path with the `v2:` context
binding when the page id is part of the row key.

## What the rest of the codebase sees

Downstream callers receive frozen dataclasses:

- `ZaloRuntimeConfig` — bot token, bot webhook secret, OA app id, OA secret
  key, OA access token, OA refresh token, plus the constant
  `ZALO_BOT_API_BASE` / `ZALO_OA_API_BASE` from
  `backend/app/core/config.py`.
- `MinimaxRuntimeConfig` / `OpenRouterRuntimeConfig` — api key, base url,
  agent / safety / digest model names, the enabled flag, and the
  `default_provider` selector (`"minimax"` or `"openrouter"`).
- `FacebookRuntimeConfig` — bound to a single Page (app id, app secret, page
  id, decrypted page access token, verify token, Graph API version and base
  url). The Page access token is server-only and never serialized into API
  responses, logs, or queue payloads.

These configs flow into:

- `graph.factories.build_deps` — wires `ZaloChannelSender` per turn.
- `graph.factories._build_cached_clients` — builds `agent_llm`,
  `embedder`, and `fast_llm` once per LLM-provider version, then caches.
- `services.zalo_bot_service.ZaloBotAdminClient` — used by the admin probe
  endpoints.
- `services.zalo_oa_service.ZaloOASender` — used for outbound OA sends and
  for the profile-enrichment path that backfills OA user names/avatars.

## Caveats

- `INTEGRATION_SETTINGS_ENCRYPTION_KEY` rotation is not handled in-process;
  decrypting a row under the new key returns `InvalidTag` and the service
  logs a warning, falling back to env vars. Plan rotations with a maintenance
  window that re-writes the affected rows through the admin API.
- `v1:` rows (legacy, no AAD binding) decrypt unchanged. New per-Page tokens
  should be written through `encrypt_with_context` so they ship as `v2:`.
- The dev fallback key (`JWT_SECRET`) is intentionally forgeable in dev.
  `Settings.model_post_init` refuses to boot production with the dev default
  so a deployed instance cannot accidentally sign admin JWTs or decrypt
  production secrets with a public key.
