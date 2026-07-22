# API Reference

> REST API reference for the ChatBot (VFIC miniCRM) backend.
> See [`../docs/system-architecture.md`](system-architecture.md) for the full runtime architecture,
> [`../standards/security.md`](../standards/security.md) for auth details.

## Base URL

- **Local dev:** `http://localhost:5173/api/v1` (Vite proxy → backend)
- **Production:** `https://bot.tingting.vip/api/v1` (Caddy → FastAPI)

## Authentication

All endpoints except `/auth/login`, `/auth/refresh`, `/auth/forgot-password`,
`/auth/reset-password`, `/installation/runtime`, `/health`, `/metrics`,
`/health/queue`, and `/webhooks/*` require a JWT Bearer token.

```
Authorization: Bearer <access_token>
```

### Auth dependencies (`backend/app/api/dependencies.py`)
| Dependency | Access |
|---|---|
| `get_current_user` | Any authenticated user |
| `require_admin` | Admin role only (403 otherwise) |
| `require_recruiter` | Admin + recruiter roles (403 otherwise) |

### Token lifecycle
- **Access token:** 60 min (default). `POST /api/v1/auth/login` → `{access_token, refresh_token, token_type}`.
- **Refresh token:** 14 days (default). `POST /api/v1/auth/refresh` with refresh token → new access token.
- **Token versioning:** `user.token_version` — bumping invalidates all existing tokens for that user.

## Routes (15 route groups)

The application registers the API routers in `backend/app/main.py` under
`API_V1_PREFIX = "/api/v1"`; realtime and webhook groups keep their root paths.

| Router | Prefix | Tags | Auth | Purpose |
|---|---|---|---|---|
| `auth` | `/api/v1/auth` | `auth` | Public (login/refresh); JWT (`/me`, `/change-password`) | Login, refresh, profile, password |
| `users` | `/api/v1/users` | `users` | JWT (self); `require_admin` (CRUD) | User management |
| `conversations` | `/api/v1/conversations` | `conversations` | JWT; `require_admin` (history clear) | Inbox, messages, takeover, release |
| `leads` | `/api/v1/leads` | `leads` | JWT | Lead CRM pipeline |
| `bot_runs` | `/api/v1/bot_runs` | `bot_runs` | JWT (read-only) | Bot turn audit log |
| `knowledge` | `/api/v1/knowledge` | `knowledge` | `require_admin` | KB documents, chunks, versions |
| `projects` | `/api/v1/knowledge/projects` | `projects` | `require_recruiter` (list/get); `require_admin` (create/delete) | Product/project knowledge CRUD, direct-context sync, FAQ, features |
| `personas` | `/api/v1/knowledge/personas`, `/api/v1/knowledge/persona-assignments` | `personas` | `require_admin` | AI agent persona CRUD and adapter assignment |
| `jobs` | `/api/v1/jobs` | `jobs` | JWT (list/get); `require_admin` (create/update) | Job postings |
| `dashboard` | `/api/v1/dashboard` | `dashboard` | JWT | Dashboard metrics + recruiter attention queue |
| `performance` | `/api/v1/admin/performance` | `performance` | `require_admin` | Performance observability |
| `integrations` | `/api/v1/admin/integrations` | `integrations` | `require_admin` | Integration settings (Zalo, Messenger, LLM) |
| `installation` | `/api/v1/installation`, `/api/v1/admin/installation` | `installation` | Public-safe runtime projection; `require_admin` for lifecycle administration | Immutable installation revision lifecycle |
| `realtime` | `/realtime` | — | JWT via `?token=` or Bearer | Legacy SSE endpoint |
| `webhooks` | `/webhooks` | `webhooks` | HMAC signature (no JWT) | Zalo webhook receiver |

### Non-route endpoints (in `main.py`)
| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | None | Health check |
| `GET /metrics` | None | RQ queue depths + worker count |
| `GET /health/queue` | None | Chat-path observability |

## Response Envelope

### List responses
```json
{
  "data": [...],
  "total": 42
}
```

### Single-resource responses
Returned directly (no envelope):
```json
{
  "id": "...",
  "field": "..."
}
```

### Error responses
```json
{
  "detail": "Error message in Vietnamese"
}
```

HTTP status codes follow REST conventions: 200 (OK), 201 (Created), 204 (No Content), 400 (Bad Request), 401 (Unauthorized), 403 (Forbidden), 404 (Not Found), 409 (Conflict), 422 (Validation Error), 429 (Too Many Requests), 502 (Bad Gateway).

## Agent Thinking trace

Administrators can inspect provider-returned reasoning and selected tool names for recent chatbot
runs. Recruiters receive `403` from both trace routes.

| Method and path | Result |
|---|---|
| `GET /api/v1/conversations/{conversation_id}/bot-runs` | Lean recent-run summaries with `trace_available`; no candidate reply |
| `GET /api/v1/bot_runs/{run_id}` | One run with its versioned `decision_trace` |

A version 2 trace contains only ordered `model_turn` events. Each event pairs the reasoning text
returned by MiniMax or OpenRouter with tool names selected in that same invocation;
`reasoning_status=not_returned` means the provider exposed none. Legacy version 1 execution-summary
events remain parseable but are not presented as Agent Thinking. The contract adds no separate
prompt, candidate-answer, tool-argument, tool-result, or evidence fields. Returned reasoning is
free-form and may echo conversation context, so it is admin-only and expires after 30 days.

## Installation lifecycle and Settings configuration

The runtime endpoint provides safe metadata for the authenticated recruitment
console. Administrators manage lifecycle configuration through Settings-backed
revision operations; there is no installation setup wizard or mutable setup
workspace. An absent `installation_state` row is returned as `UNCONFIGURED`.

| Method and path | Auth | Result |
|---|---|---|
| `GET /api/v1/installation/runtime` | Public | Schema-versioned, `no-store` lifecycle projection. Draft values stay private; active-only output may include branding, locale, terminology, and capability IDs, but never persona body, policy, integration value, or audit data. |
| `GET /api/v1/admin/installation` | Admin | Current lifecycle, generation/lock metadata, current revision, current and active validation, and readiness. |
| `POST /api/v1/admin/installation/revisions` | Admin | Append a complete immutable successor revision (`201`). The request must echo the loaded `expected_lock_version`; a stale save returns `409 INSTALLATION_CONFLICT`. |
| `POST /api/v1/admin/installation/revisions/{revision_id}/validate` | Admin | Append checksum-pinned validation evidence; invalid input/reference evidence returns field-level issues. |
| `POST /api/v1/admin/installation/revisions/{revision_id}/activate` | Admin | Attempt transactional activation of the current validated revision. |
| `POST /api/v1/admin/installation/revisions/{revision_id}/rollback` | Admin | Attempt a validated same-pack rollback with a new authority generation. |
| `POST /api/v1/admin/installation/suspend` | Admin | Suspend the active installation and advance authority generation. |
| `POST /api/v1/admin/installation/resume` | Admin | Resume from current validation evidence and advance authority generation. |
| `GET /api/v1/personas/{persona_id}/versions` | Admin | Immutable persona version metadata (`id`, version, checksum, timestamp) without persona content. |
| `GET /api/v1/knowledge/persona-assignments` | Admin | Effective Agent assignment for Zalo Chatbot, Zalo OA, and Messenger. An adapter without an override inherits the global default Agent. |
| `PUT /api/v1/knowledge/persona-assignments/{provider}` | Admin | Set one adapter override with `{ "persona_id": "<uuid>" }`, or send `{ "persona_id": null }` to return that adapter to the global default. |

Installation lifecycle failures use the compatibility `detail` field plus
stable machine-readable fields:

```json
{
  "detail": "Installation revision validation failed",
  "code": "INSTALLATION_VALIDATION_FAILED",
  "lifecycle": "DRAFT",
  "issues": [
    {
      "code": "PERSONA_VERSION_NOT_FOUND",
      "message": "Persona Version Not Found",
      "path": "persona_version_id"
    }
  ]
}
```

Admin request-shape failures use the same envelope with HTTP `422` and
`lifecycle: "UNKNOWN"`. Other lifecycle mappings are `404`
`INSTALLATION_REVISION_NOT_FOUND`; `409` `INSTALLATION_NOT_ACTIVE`,
`INSTALLATION_CONFLICT`, `INSTALLATION_PACK_LOCKED`, or
`INSTALLATION_RUNTIME_NOT_READY`. Normal missing/insufficient JWT credentials
remain `401`/`403` through the existing auth handlers.

The code-owned recruitment pack is the only active runtime contract. Lifecycle
configuration is retained for administrator Settings, not as a multi-industry
installation flow.

Administrator-authored personas must carry an explicit policy. The current no-proactive-
follow-up path stores disabled rules with no cadence or eligible stage, but its
wire shape still requires the recruitment-specific keys `hot`, `warm`, and
`not_interested`. That hard-coded category shape is not a universal contract and
must be replaced or made capability-owned in the protected Phase 5 work before
any pack can become runtime-ready.

Revision input is closed rather than free-form. `workflow_policy` accepts only
`workflow_id`, the selected immutable `workflow_version_id` and
`workflow_version_checksum`, `handoff_mode`, and `automation_enabled`.
Creating a new revision requires a matching authored workflow version/checksum;
historical revisions with null pins remain readable but are not activation-ready.
`provider_policy` accepts only integration references, model IDs, temperature,
and output-token limit; extra fields and secret-shaped values are rejected.
Locale accepts a bounded BCP-47 language tag with optional script and region
(for example `vi`, `zh-Hant`, or `zh-Hant-TW`), timezone must be an IANA name,
and currency must be present in the server's current ISO-4217 alphabetic-code
allowlist.

A `READY` response is not based only on the stored lifecycle flag. The service
rechecks the active revision, validation, pack contract, immutable persona and
template checksums, required integrations, and checksum-pinned active-KB
evidence against PostgreSQL before reporting readiness.

## Facebook Messenger settings flow

The recruiter console now exposes a dedicated Messenger section under
`/settings` for Page authorization and activation. This flow is admin-only
except for the browser redirect callback, which cannot carry the app's JWT and
is therefore authenticated by one-time state plus the admin session metadata
stored with it.

| Method and path | Auth | Result |
|---|---|---|
| `GET /api/v1/admin/integrations/facebook` | Admin | Returns the active/archived Page projection. The response masks the Page ID suffix; history is preserved. |
| `POST /api/v1/admin/integrations/facebook/oauth/start` | Admin | Returns `authorization_url` and stores short-lived OAuth state bound to the initiating admin id and `token_version`. |
| `GET /api/v1/admin/integrations/facebook/oauth/callback` | Public redirect | Validates the one-time state server-side, exchanges the code, stores an encrypted opaque flow capsule in Redis, and redirects back to `/#/settings` with `facebook_oauth_status` plus either `facebook_oauth_flow_id` or `facebook_oauth_error`. |
| `GET /api/v1/admin/integrations/facebook/oauth/pages?flow_id=...` | Admin | Returns the safe Page list for the current authenticated admin session. |
| `POST /api/v1/admin/integrations/facebook/oauth/complete` | Admin | Consumes the flow once, activates the selected Page, and invalidates the pending session record. |
| `POST /api/v1/admin/integrations/facebook/test` | Admin | Probes the active Page connection. |
| `DELETE /api/v1/admin/integrations/facebook` | Admin | Disconnects the single active Page server-side; no `page_id` query parameter is required. |

The callback redirect target is built from the first allowlisted
`facebook_callback_allowlist` origin (localhost fallback in dev). The frontend
strips the Messenger callback flags from the hash after reading them, so the
URL returns to a clean `#/settings` state after page selection or error
handling.

## Rate-Limited Endpoints

| Endpoint | Limit |
|---|---|
| `POST /api/v1/auth/login` | Rate-limited (IP-based) |
| `POST /api/v1/auth/refresh` | Rate-limited |
| `POST /api/v1/auth/forgot-password` | Rate-limited |
| `POST /api/v1/auth/reset-password` | Rate-limited |

Rate limiting via `backend/app/core/ratelimit.py` (`enforce_rate_limit`, `enforce_rate_limit_key`).

## Webhook Authentication

Zalo webhooks (`/webhooks/*`) are authenticated via **HMAC signature validation** — not JWT. The webhook handler verifies the request signature against the shared secret before processing.

- **Never disable signature validation.**
- For local testing, use the mock server: `backend/mock_servers/`.

## Socket.IO Events

Socket.IO server at `/socket.io/` (mounted via `socketio.ASGIApp` in `main.py`).

### Connection
- **Auth:** JWT in handshake `auth.token` or `Authorization: Bearer` header.
- **Rooms:** `user:{user_id}` (auto-joined on connect), `conv:{conversation_id}`, `lead:{lead_id}`.

### Server → Client events
| Event | Payload | Purpose |
|---|---|---|
| `message.created` | Serialized message | New message (bot or candidate) |
| `presence join` | `{user_id, conversation_id}` | Recruiter joined conversation |
| `presence leave` | `{user_id, conversation_id}` | Recruiter left conversation |
| `presence typing` | `{user_id, conversation_id}` | Recruiter is typing |
| `presence stop typing` | `{user_id, conversation_id}` | Recruiter stopped typing |

### Client → Server events
| Event | Payload | Purpose |
|---|---|---|
| `join conversation` | `{conversation_id}` | Subscribe to conversation room |
| `leave conversation` | `{conversation_id}` | Unsubscribe from conversation room |
| `join lead` | `{lead_id}` | Subscribe to lead room |
| `leave lead` | `{lead_id}` | Unsubscribe from lead room |
| `presence heartbeat` | — | Keep presence alive |
| `presence typing` | `{conversation_id}` | Notify others of typing |
| `presence stop typing` | `{conversation_id}` | Notify others of stopped typing |

## Recruiter Attention Dashboard

### `GET /api/v1/dashboard/attention`

Read-only, viewer-scoped attention queue replacing the legacy client-side dashboard
aggregation. Returns five exact counters plus two bounded, deduplicated queues so a
recruiter sees who needs attention now, why, and what action comes next.

**Auth:** JWT (admin sees all; recruiter sees own + unassigned).

**Snapshot consistency:** all reads execute inside one transaction at REPEATABLE READ
(`SET LOCAL transaction_isolation`), so the five counters and the bounded queue rows
share a single snapshot — no badge/queue disagreement under concurrent webhook writes.

**Performance budget:** ≤ 3 DB round-trips per request (1 counters query + 2 bounded
queue reads), backed by a per-viewer Redis cache (~30s TTL, `dashboard:attention:{scope}`).

**Contact information:** each row returns the lead's full `phone` so the authenticated
recruiter can follow up directly. The response contains **no `latest_message` body**
(candidate-authored free text may contain third-party PII and is not needed to
prioritize work). Use `last_inbound_at` for elapsed-time display.

**Response contract** (`app/schemas/dashboard.py`):

```json
{
  "updated_at": "2026-07-12T10:30:00Z",
  "counters": {
    "needs_reply": 12,
    "overdue": 4,
    "due_today": 7,
    "priority": 3,
    "unread": 9
  },
  "immediate": [AttentionItem, ...],
  "today": [AttentionItem, ...]
}
```

Each queue is bounded to 8 rows; counters cover the full filtered set. Each
`AttentionItem` carries `key`, `reason`, `urgency_at`, `conversation_id?`, `lead_id?`,
`name?`, `phone?`, `desired_job?`, `lead_stage?`, `lead_score?`,
`last_inbound_at?`, `due_at?`, `delivery_status?`, and `action`
(`OPEN_CONVERSATION` | `CALL`). A candidate appears once, under its highest-priority reason.

**Reason precedence** (1 = highest): `DELIVERY_REVIEW` → `HUMAN_ESCALATION` →
`REPLY_OVERDUE` → `FOLLOWUP_OVERDUE` → `WAITING_REPLY` → `PRIORITY_NO_ACTION` →
`FOLLOWUP_TODAY` → `UNREAD` → `STALLED`.

**Approved thresholds:**
- Unanswered inbound becomes overdue after **30 minutes**.
- Hot or `REGISTERED` candidate (within **7 days** of creation) needs action after **24 hours**
  without a recruiter response when no future follow-up or `next_action_at` exists.
  The 7-day window prevents terminal `REGISTERED` leads from flooding the priority counter.
- Active candidate becomes stalled after **48 hours** without activity (lead update OR
  linked-conversation inbound/outbound).
- Latest failed/ambiguous (`SEND_UNKNOWN`) delivery is review-only; no one-click resend.

**Join & dedup contract:** `leads` and `conversations` have no foreign key (only a
nullable `zalo_id == zalo_chat_id` soft match) and independent `assigned_recruiter_id`
columns. Viewer scope is applied to **both** the anchor and enrichment tables per reason.
`zalo_id IS NULL` leads are eligible only for lead-anchored reasons.

**Caveat — `unread_count` lag:** `Conversation.unread_count` is reset server-side only on
`markAsRead`; it lags the frontend's optimistic read state. The UNREAD counter reflects
the server view, which may differ momentarily from the inbox display.

### `GET /api/v1/conversations?reason=<REASON_ENUM>`

Continuation filter for the attention dashboard's "Mở hộp thư" drill-down. Accepts any
`AttentionReason` enum value and delegates to `ConversationService.list_by_attention_reason`,
which reuses the same reason predicates as `/dashboard/attention` (DRY). Returns the
standard `ConversationListResponse` shape. When `reason` is absent, the existing
`list_conversations` behavior is unchanged.

### Conversation adapter scope

`GET /api/v1/conversations` accepts an optional `channel_provider` query value:
`zalo_bot` or `zalo_oa`. The scope composes with search, `needs_attention=true`,
and `reason=<REASON_ENUM>`. Attention-reason totals and pagination are calculated
after provider filtering, so pages never mix adapters.

`GET /api/v1/conversations/needs-attention` accepts the same optional scope and
returns `{"count": <number>}`. Omitting `channel_provider` keeps the aggregate
count used by the global navigation badge. Unsupported providers return `422`.
The Messenger settings flow lives under `/settings` and is documented below.

## Custom DataProvider Methods

The frontend dataProvider (`frontend/src/components/atomic-crm/providers/rest/dataProvider.ts`) extends react-admin with custom methods:

| Method | Purpose |
|---|---|
| `sendHumanReply` | Recruiter sends a manual reply to a candidate |
| `takeOverConversation` | Recruiter takes over a conversation from the bot |
| `releaseConversation` | Recruiter releases conversation back to the bot |
| `setConversationMode` | Toggle conversation mode (bot/manual) |
| `clearConversationHistory` | Clear conversation history (admin only) |
| `markAsRead` | Mark conversation as read |
| `createProfile` | Create user profile |
| `disableUser` | Disable a user account |
| `enableUser` | Enable a user account |
| `getConfiguration` | Get app configuration |
| `updateConfiguration` | Update app configuration |

## Knowledge ingestion templates

All endpoints below are admin-only and live below `/api/v1/knowledge`.

| Endpoint | Purpose |
|---|---|
| `GET /ingestion-template-starter-packs` | Read built-in recruitment, shopping, and logistics starter definitions. |
| `GET, POST /ingestion-templates` | List templates or create a template with its first draft version. |
| `POST /ingestion-templates/preview` | Validate a proposed definition against supplied text without persisting a template. |
| `GET /ingestion-templates/{template_id}/versions` | List template versions. |
| `POST /ingestion-templates/{template_id}/drafts` | Clone the current published version into a mutable draft. |
| `PATCH /ingestion-template-versions/{version_id}` | Update a draft using its current `revision`. A stale revision returns `409`. |
| `POST /ingestion-template-versions/{version_id}/preview` | Preview a persisted draft. Publishing requires the exact preview checksum. |
| `POST /ingestion-template-versions/{version_id}/publish` | Compile and immutably publish a draft. |
| `POST /ingestion-template-versions/{version_id}/deprecate` | Stop future assignment of a published version. |
| `GET, PUT /projects/{project_id}/ingestion-template-assignment` | Read or append a project's template assignment. The PUT requires the next assignment revision. |
| `GET /ingestion-runs/{run_id}` | Inspect a KB-version ingestion run. |
| `GET /projects/{project_id}/kb/versions/{version_id}/ingestion-runs` | List reviewable runs for one KB version. |
| `POST /ingestion-runs/{run_id}/approve` | Approve a run requiring review. |
| `POST /ingestion-runs/{run_id}/reject` | Reject a run without exposing its facts. |
| `GET /projects/{project_id}/structured-facts` | Read generic facts from the project’s active KB release only. |

Template previews are validation/extraction simulations. They do not activate a KB
release or expose candidate-facing answers. Validation failures return `422`; stale
draft or assignment revisions and invalid lifecycle transitions return `409`.

## Direct-context single-page sync

The admin-only Project API exposes the single-page knowledge file plus the
additive Google Sheet sync control plane. These routes apply only when the
Project owns a `DIRECT_CONTEXT` knowledge base.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/knowledge/projects/{project_id}/single-page` | Read the current direct-context page, including the raw text. |
| `PUT /api/v1/knowledge/projects/{project_id}/single-page` | Replace the direct-context page manually. |
| `GET /api/v1/knowledge/projects/{project_id}/single-page/external-sources` | List the Google Sheet sync rows. |
| `POST /api/v1/knowledge/projects/{project_id}/single-page/external-sources` | Create the additive sync row from one public HTTPS Google Sheet URL. The backend resolves one exact `gid`; fragment `#gid=` takes precedence over `?gid=`. |
| `POST /api/v1/knowledge/projects/{project_id}/single-page/external-sources/{source_id}/run-now` | Trigger the same sync immediately from the console. Returns `{"job_id": "..."}` and enforces the 5-minute cooldown with `429 run_now_cooldown`. |
| `DELETE /api/v1/knowledge/projects/{project_id}/single-page/external-sources/{source_id}` | Remove the sync row. The direct-context page remains until another successful replacement. |

List rows expose the operational state used in the console: `sheet_url`,
`sheet_gid`, `auto_sync_enabled`, `consecutive_failures`, `last_status`,
`last_error`, `last_row_count`, `last_content_hash`, `last_synced_at`,
`created_at`, and `updated_at`.

Sync failures preserve the previous page. `FAILED` records an error code on the
row, `NO_OP` records an unchanged content hash, and `OK` records the new hash
and row count after atomic replacement.

## Project category authority

The admin-only Project API exposes explicit authority transitions for RAG category data.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/knowledge/projects/{project_id}/categories/cutover` | With JSON body `{ "confirmation": "CUTOVER" }`, require every category to be active or explicitly cleared, snapshot the prior authority, and switch retrieval to category revisions. |
| `POST /api/v1/knowledge/projects/{project_id}/categories/rollback` | With JSON body `{ "confirmation": "ROLLBACK" }`, restore the saved legacy authority if category pointers have not changed since cutover. |

Staging, activation, and clear operations do not implicitly change Project-wide retrieval
authority. Failed or stale workers preserve the prior active pointers and expose stable,
sanitized failure codes rather than source or provider content.

The category clear/cutover/rollback request bodies all use the same required field name:
`confirmation`.

### Resource path mapping
| react-admin resource | API path |
|---|---|
| `knowledge_sources` | `/api/v1/knowledge/documents` |
| `projects` | `/api/v1/knowledge/projects` |
| `personas` | `/api/v1/knowledge/personas` |
