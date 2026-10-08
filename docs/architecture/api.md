# API Reference

> REST API reference for the ChatBot (VFIC miniCRM) backend.
> See [`../docs/system-architecture.md`](system-architecture.md) for the full runtime architecture and auth details.

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

### Auth dependencies (`backend/app/api/auth_dependencies.py`)
| Dependency | Access |
|---|---|
| `get_current_user` | Any authenticated user |
| `require_admin` | Admin role only (403 otherwise) |
| `require_recruiter` | Admin + recruiter roles (403 otherwise) |

### Token lifecycle
- **Access token:** 60 min (default). `POST /api/v1/auth/login` → `{access_token, refresh_token, token_type}`.
- **Refresh token:** 14 days (default). `POST /api/v1/auth/refresh` with refresh token → new access token.
- **Token versioning:** `user.token_version` — bumping invalidates all existing tokens for that user.

Account lifecycle changes refresh and lock the current account before applying
the last-active-admin policy. Security writes serialize the session-generation
bump against the current row, and password changes verify the current locked
password hash. For user PATCH requests, explicit `null` for `email`, `role`, or
`disabled` is treated as omission; `full_name: null` clears the optional name.
OTP password reset refreshes the locked account and consumes/rejects a challenge
if the account's current email no longer owns that challenge. It increments the
current session generation, including security changes committed after the
request first loaded the account.
An email uniqueness conflict remains a conflict response after transaction
rollback, rather than attempting an implicit async reload of expired attributes.

## Routes (14 route groups)

The application registers the API routers in `backend/app/main.py` under
`API_V1_PREFIX = "/api/v1"`; realtime and webhook groups keep their root paths.

| Router | Prefix | Tags | Auth | Purpose |
|---|---|---|---|---|
| `auth` | `/api/v1/auth` | `auth` | Public (login/refresh); JWT (`/me`, `/change-password`) | Login, refresh, profile, password |
| `users` | `/api/v1/users` | `users` | JWT (self); `require_admin` (CRUD) | User management |
| `conversations` | `/api/v1/conversations` | `conversations` | JWT; `require_admin` (history clear) | Inbox, messages, takeover, release, bot-reply nudges |
| `leads` | `/api/v1/leads` | `leads` | JWT | Lead CRM pipeline |
| `knowledge` | `/api/v1/knowledge` | `knowledge` | `require_admin` | KB documents, chunks, versions |
| `projects` | `/api/v1/knowledge/projects` | `projects` | `require_recruiter` (list/get); `require_admin` (create/delete) | Product/project knowledge CRUD, direct-context sync, FAQ, features |
| `jobs` | `/api/v1/jobs` | `jobs` | JWT (list/get); `require_admin` (create/update) | Job postings |
| `dashboard` | `/api/v1/dashboard` | `dashboard` | JWT | Dashboard metrics + recruiter attention queue |
| `performance` | `/api/v1/admin/performance` | `performance` | `require_admin` | Response-time p50/p95 + trend and phone-capture conversion |
| `notifications` | `/api/v1/notifications` | `notifications` | JWT | Web Push subscription handles (VAPID key, subscribe, unsubscribe, self-test); alerts are sent server-side |
| `integrations` | `/api/v1/admin/integrations` | `integrations` | `require_admin` | Integration settings (Zalo, Messenger, LLM, email digest) |
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

## Lead profile updates

`PATCH /api/v1/leads/{lead_id}` updates a lead and returns the complete
`LeadOut` resource. The closed request shape accepts `name`, `phone`,
`birth_year`, `age`, `living_area`, `address`, `gender`, `region`,
`desired_job`, `years_experience`, `expected_salary`, `notes`, `lead_score`,
and `lead_stage`.

The recruiter console sends the currently loaded `version` with candidate
profile edits. The server applies those edits with compare-and-increment
optimistic concurrency; a stale version returns `409` with a Vietnamese
conflict detail so the client can refetch. Successful updates emit
`lead.updated` to the lead realtime room. Internal callers may omit `version`,
but interactive clients must include it to avoid lost updates. Stage workflow
actions remain separate from the candidate profile form.

Candidate-authored phone evidence is recorded before generation. Explicit
rejection of the matching current mobile clears `phone` and increments the
lead version; its old value remains in the audit event. Explicit correction or
reconfirmation restores the canonical field. Delayed candidate extraction
cannot undo newer phone evidence. Ordinary absent/null extractor values retain
the existing merge behavior; recruiter profile edits keep the version contract
above.

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

Installation lifecycle failures use the compatibility `detail` field plus
stable machine-readable fields:

```json
{
  "detail": "Installation revision validation failed",
  "code": "INSTALLATION_VALIDATION_FAILED",
  "lifecycle": "DRAFT",
  "issues": [
    {
      "code": "TEMPLATE_VERSION_NOT_FOUND",
      "message": "Template Version Not Found",
      "path": "template_version_refs"
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

The agent persona is a code constant, not administrator-authored content. Its
body and its identity/opening rules live in
`backend/app/prompts/vfic_persona.py`; there is no persona table, no persona
schema, and therefore no admin-authored persona policy to validate. The
manifest's fail-closed persona check is `current_persona_checksum()` in
`backend/app/services/installation/validation.py`, which hashes the body the
running code ships (`sha256_json({"body_md": ...})`) and compares the recorded
`persona_checksum` against it, so shipping a persona edit without
re-validating the manifest still invalidates it.

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
rechecks the active revision, validation, pack contract, the code-derived persona
checksum and immutable template checksums, required integrations, and
checksum-pinned active-KB evidence against PostgreSQL before reporting
readiness.

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
| `POST /api/v1/admin/integrations/facebook/test` | Admin | Probes the active Page connection: Page-token validity plus the app's webhook subscription on the Page (`app_subscribed`; `healthy=false` with an actionable error when the subscription is missing). |
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

The **Cần can thiệp** cohort has one authoritative membership rule: the
conversation is `OPEN`, its mode is `HUMAN`, and its latest candidate inbound is
newer than the latest outbound reply (or no outbound exists). `BOT` and
`SEMI_AUTO` conversations are excluded until a real state transition changes
the mode to `HUMAN`. The same rule backs `needs_reply`, the inbox
`needs_attention=true` filter, the topbar count, and the conversation reason
deep links.

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

Delivery and read receipts advance only messages with an exactly matching
provider message ID. An uncorrelated receipt cannot establish delivery for an
id-less `SEND_UNKNOWN` send. When only a prefix of a split answer was accepted,
the logical message remains `SEND_UNKNOWN` even if the accepted prefix later
receives an acknowledgment. These uncertain sends require review and are not
automatically replayed.

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
`zalo_bot`, `zalo_oa`, `facebook_messenger` or `tingting_oa`. `tingting_oa` is not a
provider but the employee-support Zalo OA account, so it narrows `zalo_oa` to the
`tingting` account key; the plain `zalo_oa` badge excludes that key, keeping the two
OA badges disjoint. The scope composes with search, `needs_attention=true`,
and `reason=<REASON_ENUM>`. Attention-reason totals and pagination are calculated
after provider filtering, so pages never mix adapters.

`GET /api/v1/conversations/needs-attention` accepts the same optional scope and
returns `{"count": <number>}`. Omitting `channel_provider` keeps the aggregate
count used by the global navigation badge. This count uses the same open
Human-mode + unanswered-inbound rule as the dashboard. Unsupported providers return `422`.
The Messenger settings flow lives under `/settings` and is documented below.

### `GET /api/v1/conversations/by-zalo-ids?ids=<comma-separated ids>`

Viewer-scoped batch lookup used by the recent-candidate dashboard. It accepts
1–200 deduplicated Zalo chat IDs and returns every matching conversation in
newest-updated order using the standard `ConversationListResponse` shape. The
dashboard uses the newest conversation for drill-down and may use an OA contact
from the same identity set for the candidate's profile name and avatar.

## Custom DataProvider Methods

The frontend data provider
(`frontend/src/components/atomic-crm/providers/rest/dataProvider.ts`) extends
react-admin with custom methods. Conversation reply transport is implemented by
`frontend/src/components/atomic-crm/conversations/infrastructure/http-human-reply-adapter.ts`;
all methods share `frontend/src/lib/apiClient.ts`.

| Method | Purpose |
|---|---|
| `getBotRunDetail` | Read one bot run's facts (conversation, timing, outcome) |
| `sendHumanReply` | Recruiter sends a manual reply to a candidate |
| `retryHumanReply` | Retry a failed recruiter reply |
| `takeOverConversation` | Recruiter takes over a conversation from the bot |
| `releaseConversation` | Recruiter releases conversation back to the bot |
| `setConversationMode` | Toggle conversation mode (bot/manual) |
| `clearConversationHistory` | Clear conversation history (admin only) |
| `markAsRead` | Mark conversation as read |
| `createProfile` | Create user profile |
| `disableUser` | Disable a user account |
| `enableUser` | Enable a user account |
| `resetUserPassword` | Set a new password for a user (admin only) |
| `signUp` | Reject public sign-up; accounts are admin-provisioned |

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

## Project knowledge export

`GET /api/v1/knowledge/projects/{project_id}/knowledge-export` is admin-only.
Project list and detail responses include the server-owned boolean
`category_authority_started`, which enables the migration action while a
legacy RAG project still uses its previous published knowledge.
It returns a UTF-8 Markdown attachment named `kb-<safe-project-slug>.md`, with
`Cache-Control: no-store`. `Content-Disposition` is exposed through CORS so
the authenticated console can retain the download filename.

The export reads one database snapshot of the currently authoritative sources:
the saved direct-context page, active category sources in catalog order after
category cutover, or published text files in the active legacy KB version before
cutover. Pending, failed, archived, cleared, unrelated, and shadow sources are
excluded. Unsaved browser drafts are never sent to this endpoint. This is a
content export, not a database backup of revision history, embeddings, or
runtime configuration.

Missing projects return `404`; projects without exportable saved knowledge
return `409`. Non-admin accounts cannot export (`403`).

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

## Per-project external API

The admin-only integration surface for the outbound `call_project_api` path
(see ADR-0011). All three routes require an admin session.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/knowledge/projects/{project_id}/external-api` | Masked view incl. `chatbot_readiness` (`ready` + stable blocker codes), key never returned. |
| `PUT /api/v1/knowledge/projects/{project_id}/external-api` | Full replace; tri-state `api_key` (absent keeps, `""` clears). |
| `POST /api/v1/knowledge/projects/{project_id}/external-api/test` | One real call through the stored integration (same validation, dedupe/throttle and egress as the bot); returns `{state, status_code, detail, text}`; rate-limited per admin user. |

## Project category authority

The admin-only Project API exposes explicit authority transitions for RAG category data.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/knowledge/projects/{project_id}/categories/cutover` | With JSON body `{ "confirmation": "CUTOVER" }`, require every category to be active or explicitly cleared, snapshot the prior authority, and switch retrieval to category revisions. |
| `POST /api/v1/knowledge/projects/{project_id}/categories/rollback` | With JSON body `{ "confirmation": "ROLLBACK" }`, restore the saved legacy authority and category pointers, including after subsequent category updates. |

Category content is authored in Category Markdown v1: the `PUT
/api/v1/knowledge/projects/{project_id}/categories/{category_key}` body is
`{filename, content}` where `filename` ends in `.md`, `.markdown` or `.txt`
(`.yaml`/`.yml` are refused), and `content` is the category's markdown
document (`---` front-matter plus one `## <list_field>` section of
`### record: <stable-id>` blocks; `GET .../categories/{key}/template` returns
the fill-in questionnaire template as `text/markdown`). Document uploads accept
`.txt`, `.text`, `.md`, `.markdown`, `.csv`, `.tsv`, `.log`, `.json`, `.rst`,
`.docx` and `.xlsx`. Extensionless text filenames require a
supported text MIME type. CSV/JSON are read as source text, without assuming a
recruitment schema. Text decoding is strict UTF-8 by default, with UTF-8/16/32
BOM support and an allowlisted declared charset for legacy text. Invalid,
truncated, empty or binary data is rejected instead of replacing characters.
Uploads are limited to 20 MB; YAML and PDF are not accepted.

`POST /api/v1/knowledge/projects/{project_id}/categories/{category_key}/clear`
accepts an optional `expected_revision_no` query parameter. The service compares
it with the latest revision under the publication locks and returns `409` if it
changed. Migration uses `0` only to initialize a genuinely unwritten category;
a concurrent administrator write is preserved. Explicit manual clears retain
their existing behavior when the parameter is omitted.

`GET /api/v1/knowledge/projects/{project_id}/knowledge-template` downloads
`mau-kb-du-an.md` as a `text/plain; charset=utf-8` attachment for recruiters and
admins. The console button is **Tải mẫu KB**. Its client reads the response as
text, rather than JSON; OpenAPI declares the text response as well.

Category records are Project-scoped. Templates and typed payloads have no
`job_ids` or `jobs_ids` association fields. Jobs records also omit `vacancies`
and `employment_type`, including null placeholders. No category requires an active
Jobs category to validate. Legacy structural fields are ignored during parsing
and omitted from new stored category/direct-page sources, editor reads and KB
exports, document chunk/digest/search responses and source downloads. Historical revision identities remain unchanged. Derived role filters
use a scalar only when all records in the category agree; conflicting or absent
values remain unknown while the source facts remain retrievable.
KB publication preserves existing recruitment capacity counts; a newly derived
role has unknown capacity rather than an invented vacancy count.

`POST /api/v1/knowledge/documents/upload-file` accepts an optional multipart
`category_plan` JSON field alongside `file` and `project_id`:
`{"writes":[{"key":"jobs","filename":"jobs.md","content":"..."}]}`.
The plan contains at most twelve unique category keys; the backend validates
the complete proposal before storing it. This admin-only operation retains
the source and queues a resumable project training batch. Alternatively,
`auto_extract=true` retains the original source and queues automatic extraction
on the worker. The console uses this path for every project brief; its browser
parser only proposes form values and cannot limit the categories reviewed.
Omitting both fields preserves the existing plain document upload contract.

Automatic extraction reviews the complete text in overlapping sections of up
to 12,000 characters, checks all twelve category contracts, and retains source
quotes for every record. Missing information is reported and does not clear an
existing category. Unmatched evidence, invalid schemas, provider failures and
sources without recruitment facts produce a failed receipt, without publishing
a partial mapping. A section checkpoint resumes validated extraction after a
failure; the retained plan also resumes category preparation. The processing
budget is 200 sections and 2,000,000 category-content characters; oversized
sources fail explicitly with a request to split the file. Administrator edits
to categories or features after upload supersede the automatic source instead
of being overwritten. Identical reuploads reuse a source only while its intent
is still current.
Worker feature extraction uses the same bounded source sections with its own
retry checkpoints. Contradictory values are retained for review with
`needs_clarification=true`; they do not replace an existing reliable feature.

Document responses expose an additive `project_training` receipt, or `null`
for uploads without training intent. Its `status` is `QUEUED`, `PROCESSING`, `COMPLETED`,
or `FAILED`; `planned` lists categories extracted from the source, `current`
identifies the current category, `completed` lists
confirmed category keys, and `error` is a sanitized failure message. Read it
alongside `source_sections_total`, `source_sections_completed`,
`covered_categories` and `missing_categories` for automatic extraction progress
through `GET /api/v1/knowledge/documents/{id}`. Retry a retained failed source
through `POST /api/v1/knowledge/documents/{id}/process`. An accepted upload
continues in the worker when the browser disconnects; a `201` upload response
is queue acceptance rather than proof that training has completed. Activating
an inactive project returns `409` while its latest non-archived training source
is unfinished or failed; it must be `PUBLISHED` with a `COMPLETED` receipt.
Existing active projects can still be edited during replacement processing.
Prepared category evidence and extracted feature values remain private until
the entire source publishes in one transaction. In category authority,
`COMPLETED` confirms all proposed categories, features, and applicable derived projections together;
a failed source does not partially replace published data. Categories omitted
from a plan retain their existing active content. If a manual category edit
invalidates a retained source snapshot, uploading that same brief creates a
fresh source. Independently retrying an unfinished source-owned category returns
`409` with guidance to retry the source batch.
For a Project using legacy authority, the completed receipt instead includes
the additive `requires_cutover: true` flag. Categories and source-owned feature
values remain prepared until explicit category cutover; the existing candidate
knowledge and discovery card stay live. The flag defaults to `false` for older
receipts and category-authoritative publication. Rollback restores adopted
feature rows and marks the source as awaiting cutover again.
Successful cutover marks unadopted completed source-owned feature intents
`SUPERSEDED` and clears their `requires_cutover` flag. Actual independent feature
edits or feature supersession make identical reupload a fresh intent; passive
feature-list reads do not. Pending and failed training receipts retain their
existing state.

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
