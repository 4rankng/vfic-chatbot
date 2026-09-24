---
id: ARCH-07
title: "`api/integrations.py` (1353 LOC) carries provider business logic, including a raw httpx OAuth POST"
severity: medium
area: architecture
labels: [tech-debt]
effort: M
status: todo
column: TODO
opened: 2026-09-24
---

# ARCH-07 — `api/integrations.py` (1353 LOC) carries provider business logic, including a raw httpx OAuth POST

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** TODO

## Problem

The router holds the Zalo webhook sync policy, a four-layer credential diagnostic that issues a raw httpx POST to the OAuth token endpoint, the whole Facebook OAuth flow with a Redis-backed flow store, and schema mapping. None of that is an HTTP concern.

## Evidence

- `backend/app/api/integrations.py:295-310` — a raw `httpx` POST to `https://oauth.zaloapp.com/v4/oa/access_token` inside `test_zalo_oa`, interpreting `error == -14004`.
- `backend/app/api/integrations.py:96-121` — `_sync_bot_webhook` pushes the webhook secret to Zalo via `setWebhook` with change-detection policy; `:406-456` — `_probe_and_record` provider probe plus persistence.
- `backend/app/api/integrations.py:708-1012` — the Facebook OAuth flow: `_redis:708`, `_fb_callback_url:718`, `_facebook_oauth_coordinator:749` (Redis-backed flow store, `secrets.token_urlsafe` state), token exchange `:859`, `subscribe_app_to_page:964`.
- `backend/app/api/integrations.py:1159-1252` — `disconnect_facebook` calls `unsubscribe_app_from_page:1202` inline; `:1238` — `_assignments_out` schema mapping.

## Impact

The highest-risk credential flows in the product live in the transport layer, so they cannot be exercised without HTTP and the raw httpx call bypasses the `get_integration_http_client` abstraction that the rest of the codebase uses.

## Suggested fix

Natural seam: the repo already has the right home — `app/integrations/facebook_oauth/`, whose `application.py:20,32` define the `FacebookOAuthStateStore`/`FacebookOAuthFlowStore` Protocols. Extract `services/integrations/zalo_diagnostics.py` (the 4-layer OA probe, the raw OAuth POST and the Bot probe) and `services/integrations/facebook_oauth_flow.py` (flow orchestration, Redis state, subscribe/unsubscribe); the router then parses the body, calls the service, maps the domain error and returns the response model. That is also what lets the raw `httpx` call at `:295` move behind `get_integration_http_client`.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
