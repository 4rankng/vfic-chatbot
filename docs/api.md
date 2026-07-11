# API Reference

> REST API reference for the ChatBot (VFIC miniCRM) backend.
> See [`../docs/system-architecture.md`](system-architecture.md) for the full runtime architecture,
> [`../standards/security.md`](../standards/security.md) for auth details.

## Base URL

- **Local dev:** `http://localhost:5173/api/v1` (Vite proxy → backend)
- **Production:** `https://bot.tingting.vip/api/v1` (Caddy → FastAPI)

## Authentication

All endpoints except `/auth/login`, `/auth/refresh`, `/auth/forgot-password`, `/auth/reset-password`, `/health`, `/metrics`, `/health/queue`, and `/webhooks/*` require a JWT Bearer token.

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

## Routes (14 routers)

All routers registered in `backend/app/main.py` under `API_V1_PREFIX = "/api/v1"`.

| Router | Prefix | Tags | Auth | Purpose |
|---|---|---|---|---|
| `auth` | `/api/v1/auth` | `auth` | Public (login/refresh); JWT (`/me`, `/change-password`) | Login, refresh, profile, password |
| `users` | `/api/v1/users` | `users` | JWT (self); `require_admin` (CRUD) | User management |
| `conversations` | `/api/v1/conversations` | `conversations` | JWT; `require_admin` (history clear) | Inbox, messages, takeover, release |
| `leads` | `/api/v1/leads` | `leads` | JWT | Lead CRM pipeline |
| `bot_runs` | `/api/v1/bot_runs` | `bot_runs` | JWT (read-only) | Bot turn audit log |
| `knowledge` | `/api/v1/knowledge` | `knowledge` | `require_admin` | KB documents, chunks, versions |
| `projects` | `/api/v1/knowledge/projects` | `projects` | `require_recruiter` (list/get); `require_admin` (create/delete) | Product/project CRUD, FAQ, features |
| `personas` | `/api/v1/knowledge/personas` | `personas` | `require_admin` | AI agent persona CRUD |
| `jobs` | `/api/v1/jobs` | `jobs` | JWT (list/get); `require_admin` (create/update) | Job postings |
| `dashboard` | `/api/v1/dashboard` | `dashboard` | JWT | Dashboard metrics |
| `performance` | `/api/v1/admin/performance` | `performance` | `require_admin` | Performance observability |
| `integrations` | `/api/v1/admin/integrations` | `integrations` | `require_admin` | Integration settings (Zalo, LLM) |
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

### Resource path mapping
| react-admin resource | API path |
|---|---|
| `knowledge_sources` | `/api/v1/knowledge/documents` |
| `projects` | `/api/v1/knowledge/projects` |
| `personas` | `/api/v1/knowledge/personas` |
