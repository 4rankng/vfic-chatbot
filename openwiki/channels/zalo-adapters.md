---
type: integration
title: Zalo Bot Platform and Official Account adapters
description: The two webhook endpoints, their signature schemes, ingress normalization, dispatch path, and the rule that Zalo adapters are intentionally thin so the rest of the app stays channel-neutral.
tags: [zalo, bot-platform, official-account, signature, channels-port, registry, dispatch]
sources:
  - id: openwiki-source-770f01d7351c567fc93944dd
    resource: repo://backend/app/api/webhooks.py
  - id: openwiki-source-fde608ffaf5fd9f13157e802
    resource: repo://backend/app/channels/dispatch.py
  - id: openwiki-source-e2411e9e1ed726452d712fb9
    resource: repo://backend/app/channels/providers/zalo_bot.py
  - id: openwiki-source-8fa107b741fce900a484d431
    resource: repo://backend/app/channels/providers/zalo_oa.py
  - id: openwiki-source-777f8d47c822b7e613188d35
    resource: repo://backend/app/channels/registry.py
  - id: openwiki-source-085098b884681cab422762c1
    resource: repo://backend/app/services/integration_settings.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
---

Zalo is the primary channel. The platform exposes two webhook surfaces —
**Bot Platform** (`/webhooks/zalo/chatbot`) and **Official Account OA 4.0**
(`/webhooks/zalo/oa`) — with different signature schemes and different
outbound APIs. The adapters are intentionally thin: provider-specific
concerns live in `app/channels/providers/`, the channels/ registry exposes
typed `TextChannelAdapter` / `TypingCapability` / `ReceiptCapability`
ports, and the rest of the app (ingress, graph, dispatch, persistence)
talks only to the ports — it never imports the Zalo modules directly.

## Webhook endpoints

Both endpoints are mounted on the FastAPI router in
`backend/app/api/webhooks.py` and live behind Caddy
(`/webhooks/* → web-<active>:8000`).

| Endpoint | Method | Channel | Auth scheme | Adapter |
|---|---|---|---|---|
| `/webhooks/zalo/chatbot` | POST | Bot Platform | `X-Bot-Api-Secret-Token` shared secret echo (HMAC compare) | `ZaloBotChannelAdapter` |
| `/webhooks/zalo/oa` | POST | OA 4.0 | URL-verification probe only; signed-event verification intentionally non-enforced (see "OA signature" below) | `ZaloOAChannelAdapter` |
| `/webhooks/facebook` | GET / POST | Messenger | `hub.mode=subscribe` challenge; `X-Hub-Signature-256` HMAC-SHA256 on raw body | `FacebookMessengerNormalizer` (see [facebook-messenger.md](../channels/facebook-messenger.md)) |

### Bot Platform signature

Inbound authenticity is verified via the `X-Bot-Api-Secret-Token`
shared-secret echo — the same value passed to Zalo's `setWebhook` as
`secret_token`. The compare uses `hmac.compare_digest` so the check is
constant-time. Outside development, a webhook with **no secret configured**
is rejected with **503** rather than accepted blind — an unauthenticated
inbound endpoint would let anyone inject messages that trigger bot turns
and lead extraction. Dev/test keeps the accept-unsigned behavior for
ergonomics.

### OA signature (intentionally non-enforced)

OA inbound signature verification is intentionally non-enforced. The held
`oa_secret_key` is the OA access-token secret, not Zalo's webhook signing
key, so the check false-rejected 100% of real events while being
non-blocking (zero protection). The module docstring documents this
decision and notes that `POST /zalo/oa/verify-signature` remains as a
diagnostic for a future cutover when a dedicated signing secret is
available.

What the OA endpoint **does** verify: the URL-verification probe. Zalo
sends an unsigned POST whose body is an empty JSON object to confirm a
newly configured webhook URL. The handler returns `{"status": "verified"}`
with 200 for that probe only; all other events proceed without
`X-Zevent-Signature` enforcement.

## Sub-second ack contract

The webhook contract with Zalo is **<1 s ack**, every time. The route
preserves that by:

1. Reading the raw body once for JSON parsing and signature verification.
2. Verifying the signature with `hmac.compare_digest` (O(n) on body size).
3. Resolving the runtime authority stamp (`InstallationService.resolve_active`)
   after signature verification and before any business write.
4. Calling `run_zalo_ingress(db, payload, enqueue=..., ...)` — which
   commits the inbound message, acquires the conversation DB lock with
   an owner token, and enqueues the bot turn onto the `webhook_high`
   queue via `enqueue_chat_turn`.

If enqueue fails (`status="start_failed"`), the route returns **503** so
Zalo retries. On success it returns **200** with the result body.

The webhook-ack latency is sampled into the SLO sliding window via
`record_webhook_ack_ms((time.time() - t0) * 1000)`. Only successful
(2xx) acks are sampled — 4xx/5xx are rejection paths with different
latency characteristics and would skew the SLO.

## Logging boundaries

- Only request size and safe event metadata are logged (`bytes=N`).
- Candidate content, provider signatures, timestamps, and identifiers
  never enter application logs.
- The body is **never** logged — it can carry candidate text.

## Adapters

`backend/app/channels/providers/zalo_bot.py:ZaloBotChannelAdapter`
implements `TextChannelAdapter` + `TypingCapability`:

- Wraps the existing `ZaloBotSender` (`app/services/zalo_bot_service.py`).
- Token rides in the URL path (Bot Platform convention); the adapter
  resolves the token via `from_config(ZaloRuntimeConfig)` per-dispatch.
- Sends typing chat actions (`send_typing`) while a turn processes.
- The Bot Platform has no delivery/read receipts — no
  `ReceiptCapability`.

`backend/app/channels/providers/zalo_oa.py:ZaloOAChannelAdapter`
implements `TextChannelAdapter` + `ReceiptCapability`:

- Wraps `ZaloOASender` (lazy refresh-aware; see
  [integrations-credentials.md](../access/integrations-credentials.md)).
- OA conversations store the scoped chat id as `oa:<user_id>`; the
  adapter owns the storage convention and strips the `oa:` prefix when
  calling the OA Send API.
- OA CS replies require **quoting an inbound message**; the adapter
  forwards `quote_message_id` from the outbound command.
- The OA channel has no typing endpoint, so it does not implement
  `TypingCapability`.
- `parse_receipt` projects already-authenticated OA webhook events
  (delivery/read) into neutral `ChannelReceipt` projections.

## Channels registry and dispatch

`backend/app/channels/registry.py:ChannelAdapterRegistry` is the single
place that knows which concrete adapters are installed. Services depend
on this class (or its protocol), never on a provider module.

- `register(adapter)` validates the provider id against
  `is_known_provider` (typo-proof).
- `get(provider)` returns the `TextChannelAdapter` or `None` (fail-closed).
  `None` is the safe "not connected" outcome — never an exception that
  could leak provider internals.
- `get_typing(provider)` and `get_receipt(provider)` return the relevant
  capability or `None`. Absence is a legitimate state (Zalo OA has no
  typing endpoint; Zalo Bot has no receipts) and means "do nothing", not
  "failure".

`backend/app/channels/dispatch.py:ChannelDispatchService` is
registry-driven and provider-neutral:

- Resolves a `TextChannelAdapter` from the registry and routes
  `OutboundTextCommand` to it.
- Compares `channel_account_generation` on the command to the active
  generation immediately before provider I/O and **suppresses stale work**
  across disconnect/reconnect/replacement.
- The runtime authority fence on the outbox row remains separate; both
  must be current for a send to proceed.

## Why the adapters are intentionally thin

- **Single ingress contract.** Whatever the channel, the graph receives
  the same `ChannelInboundMessage` shape, runs the same `run_turn`, and
  sends through the same dispatch service.
- **Provider-owned safety.** Signature verification, typing, receipts,
  and outbound URL conventions all live next to the provider client —
  one edit per Meta/Zalo policy change.
- **Token confidentiality.** Per-turn tokens are constructed from
  `IntegrationSettingsService.resolve_zalo()` and never enter queue
  payloads, logs, or API responses.
- **Fail-closed absence.** A missing adapter or missing capability is a
  legitimate "no-op" outcome, not an exception that could leak the
  underlying provider.
