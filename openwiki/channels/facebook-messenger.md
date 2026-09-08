---
type: integration
title: Facebook Messenger adapter
description: HMAC-SHA256 webhook signature, OAUTH flow that issues the page-scoped token used for outbound dispatch, the 24-hour Standard Window policy, and the channels/port isolation that keeps the rest of the app provider-neutral.
tags: [facebook-messenger, oauth, hmac, signature, standard-window, page-token, channels-port]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
sources:
  - id: openwiki-source-9835cc890236326b828ea0b7
    resource: repo://backend/app/channels/ports.py
  - id: openwiki-source-eb6a812bcd8dd1373a92f04f
    resource: repo://backend/app/channels/providers/facebook_account.py
  - id: openwiki-source-8aaa4d5d3d2a3feccd6124ea
    resource: repo://backend/app/channels/providers/facebook_messenger.py
  - id: openwiki-source-2a63b9e35dfaa59da1e81749
    resource: repo://backend/app/channels/providers/facebook_oauth.py
  - id: openwiki-source-c3ee61f6d968bb9b4da9f21b
    resource: repo://backend/app/channels/providers/facebook_policy.py
  - id: openwiki-source-ff3183ea6ca1b180d2a3f0d9
    resource: repo://backend/app/channels/providers/facebook_signature.py
  - id: openwiki-source-ec5f0d0065badbc5beea55b1
    resource: repo://backend/app/integrations/facebook_oauth/application.py
  - id: openwiki-source-085098b884681cab422762c1
    resource: repo://backend/app/services/integration_settings.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
---

Facebook Messenger is the secondary channel after Zalo. The adapter is
intentionally thin and follows the same composition pattern as the Zalo
adapters: provider-specific concerns live in `app/channels/providers/`,
the channels/ registry exposes a `TextChannelAdapter` port, and the rest
of the app (ingress, graph, dispatch, persistence) talks only to the port
— it never imports `facebook_messenger.py` directly.

## Inbound: signature verification

`backend/app/channels/providers/facebook_signature.py:verify_messenger_signature`
verifies every inbound webhook against `X-Hub-Signature-256`.

- The header is `sha256=<hexdigest>` (some integrations send bare hex; the
  verifier accepts both).
- The verifier hashes the **raw request body bytes**, never a re-serialized
  form. Re-ordering or pretty-printing JSON breaks the signature — this is
  the most common community-reported failure mode and is documented in the
  module docstring.
- The compare uses `hmac.compare_digest` (constant-time) to avoid timing
  oracles on the signature.
- A missing app secret is **not** an exception — the verifier returns
  `SignatureVerification(verified=False, reason="app_secret_not_configured")`
  so the caller decides whether dev-mode accepts unsigned traffic. A
  missing header, malformed hex, or empty digest each get a specific
  `reason` string; the verifier never logs the body or the secret.

## Inbound: normalizer

`FacebookMessengerNormalizer.normalize(payload)` returns
`(messages, ignored_reason_counts)`:

- One webhook POST may carry multiple `entry[]` blocks, each with multiple
  `messaging[]` items. Each item independently reaches a durable outcome
  (persist, ignore, dedup) — see
  `app/conversation_messaging/application/ingress.InboundIngressResult`.
- The normalizer is pure: it neither persists nor enqueues.
- Only candidate-initiated `message.text` events become
  `ChannelInboundMessage`. Echoes, postbacks, quick replies without plain
  text, attachments, stickers, and reactions are acknowledged and ignored
  with an ignored-reason counter (safe telemetry, no PII).
- Delivery and read receipts are handled separately by
  `parse_receipt` on the adapter.

## Outbound: standard messaging window

`backend/app/channels/providers/facebook_policy.py` enforces Meta's
**Standard Messaging Window** — 24 hours from the person's last inbound
to the Page. V1 deliberately uses none of the relaxed policies (message
tags, 24h+1, human agent); every outbound must be a reply within the
window.

- `MESSENGER_STANDARD_WINDOW = timedelta(hours=24)` is a code constant
  revalidated against the Messenger Platform overview on Meta API version
  bumps.
- `evaluate_send_eligibility(last_inbound_at, now)` returns a
  `PolicyDecision(allowed, reason, window_remaining_seconds)`. A `None`
  `last_inbound_at` (the person never wrote) returns
  `allowed=False, reason="no_inbound_window"` — only an inbound can open
  one. An expired window returns `allowed=False, reason="window_expired"`.
- `window_remaining_seconds` is safe for telemetry (no PII).
- Proactive / outbound sends route through this gate; a follow-up that
  missed the window is `SUPPRESSED` (acknowledged, not retried) rather
  than sent and rejected by Meta.

## OAuth and page tokens

`backend/app/channels/providers/facebook_oauth.py` is the Graph API and
OAuth client. It is imported only by the OAuth / account-lifecycle layer
(`facebook_account.py`) and the admin endpoints — never by the shared
ingress, graph, or dispatch services (they resolve through the
`ChannelAccountResolver` port).

Required permissions (revalidated against Meta docs):

- `pages_show_list`
- `pages_manage_metadata`
- `pages_messaging`
- `public_profile` (advanced access required for go-live)

The flow:

1. Admin starts the OAuth dialog (server-rendered URL with the four
   permissions, `redirect_uri`, and a server-generated state token).
2. Meta redirects back to the callback with `code` + `state`.
3. Server exchanges `code` for an access token via the Graph API.
4. Admin selects which Pages to bind (`FacebookOAuthPage` carries id,
   name, and `tasks` so the UI can verify the admin can message).
5. Per-Page long-lived tokens are persisted as
   `facebook_page_token:<page_id>` rows in `integration_settings`,
   encrypted with **AAD = page_id** (see
   [`openwiki/access/integrations-credentials.md`](../access/integrations-credentials.md)).
6. `FacebookAccountResolver.active_facebook_page()` resolves the one
   active Page; the partial unique index
   `uq_channel_accounts_one_active_facebook_messenger` enforces at most
   one active Page at the DB level (V1 single-page scope).

`FacebookPageSummary` (id, name, tasks) is the **only** shape that
crosses the boundary back to the admin UI during Page selection —
access tokens never do.

## Outbound dispatch

The outbound text path calls `graph_send_message` (re-exported from
`facebook_oauth.py`) which sends `POST /v25.0/me/messages` with the
decrypted page-scoped token. `FacebookRuntimeConfig` (resolved per turn
via `IntegrationSettingsService`) carries the page id + decrypted page
access token server-side; the value is never serialized into API
responses, logs, or queue payloads.

## Account lifecycle

`backend/app/integrations/facebook_oauth/` (application / domain /
infrastructure layers) implements the encrypted Page-selection flow:

- `FacebookOAuthStateStore.save(state, admin, ttl_seconds)` and
  `.consume(state)` keep the OAuth state + binding alive across the
  callback round-trip.
- `FacebookOAuthFlowStore.save(flow_id, flow, ttl_seconds)` /
  `.load(flow_id, admin)` / `.consume(...)` track in-progress Page
  selection flows.
- Errors are typed: `FacebookOAuthInvalidState` (state missing or
  malformed), `FacebookOAuthFlowUnavailable` (encrypted flow missing
  or invalid).
- `FacebookAccountResolver` (in `providers/facebook_account.py`) is the
  integration-side `ChannelAccountResolver` implementation; the rest of
  the app sees only `ChannelAccountRef` projections.

## Isolation guarantees

- The shared ingress / graph / dispatch services never import
  `facebook_messenger.py`, `facebook_oauth.py`, or `facebook_account.py`.
  They resolve via `ChannelAccountResolver` (the port in
  `app/channels/ports.py`).
- `FacebookMessengerNormalizer` is pure — the only side effect is the
  ignored-reason counter, which is a safe telemetry mapping.
- `FacebookAccountResolver` enforces the single-active-Page invariant
  both in code (default `active_facebook_page` query) and at the DB
  level (the partial unique index from Alembic 0047).
- Provider scoping is structural: adding a new provider (Telegram, web
  chat) requires a new entry in `channels/registry.py` and a new
  adapter — the existing graph/ingress/dispatch paths do not change.

## Why this shape

- **Single ingress contract.** Whatever the channel, the graph receives
  the same `ChannelInboundMessage` shape, runs the same `run_turn`, and
  sends through the same `ZaloChannelSender`-equivalent adapter.
- **Provider-owned safety.** The Standard Window policy is provider-
  specific and lives next to the OAuth client so a Meta API version
  bump is one edit.
- **Token confidentiality.** Page tokens are bound to the page id by
  AEAD associated data, never logged, and never serialized outside the
  per-turn `FacebookRuntimeConfig`. The admin sees only the safe
  `FacebookPageSummary` during Page selection.
