---
type: system
title: Realtime push (Socket.IO server, cross-process bridge, console)
description: How the recruiter console subscribes to per-conversation rooms via Socket.IO, how FastAPI publishes through a cross-process Redis-backed emit bridge from any process, and the room naming + presence/typing semantics.
tags: [socketio, realtime, bridge, redis-bus, conv-room, presence, typing, sse-fallback]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
---

Realtime push is what makes the recruiter console feel live: a candidate
sends a message, the bot replies, and the recruiter's open inbox
re-renders the row without polling. The implementation is a Socket.IO
server on the FastAPI web process plus a write-only emit bridge used by
the RQ workers and the web process itself. Both ends share a Redis bus,
so emits from any process fan out to every connected browser socket.

## Why Socket.IO replaced the SSE firehose

The earlier design streamed every event over a single SSE endpoint. That
worked for one recruiter but pushed every chat event through the same
heavy request path, and the SSE connection couldn't survive a web
restart without a manual page reload. The replacement is a real
WebSocket where possible (with polling fallback) and a per-process
manager that joins publishers (any process with the bridge) and
subscribers (the web process holding browser sockets) over a shared
Redis bus. The edge stays the same: Caddy's `/socket.io/*` upstream
forwards WebSocket upgrades transparently.

## Server: `backend/app/realtime/socketio.py`

A single `socketio.AsyncServer` is constructed once at module import:

```python
sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=socketio.AsyncRedisManager(settings.redis_url),
    cors_allowed_origins=settings.cors_origins_list,
    cors_credentials=True,
    transports=["websocket", "polling"],
    async_handlers=True,
)
```

`AsyncRedisManager` is the cross-process piece: it publishes and
subscribes to a Redis bus so any process with the bridge can emit and
any web process holding browser sockets will deliver the event. The
module docstring is explicit that constructing the manager does **not**
open a background listener — that starts on ASGI lifespan, which the
test suite does not run, so importing the module in tests leaks no
loop-bound connections.

### Mounting on the FastAPI app

`backend/app/main.py`:

```python
import socketio
from app.realtime.socketio import sio as _vfic_sio
app = socketio.ASGIApp(_vfic_sio, other_asgi_app=app)
```

The mount happens **after** every router / middleware is registered
so the construction cost stays out of test collection's import path.
Caddy forwards `/socket.io/*` to the active web color over the standard
`reverse_proxy` directive — `wss://<origin>/socket.io/` works with no
edge change.

### Authentication

`authenticate_socket_token(auth, headers, db)` verifies the connect
credentials. The browser connects with `{ auth: { token } }`; the
handler calls the same `get_user_from_token` used by REST, refuses on
failure via `ConnectionRefusedError`, and rooms the connection by user
and (on demand) by conversation. The docstring notes this replaces the
SSE `?token=` workaround, so verification logic cannot drift between
REST and Socket.IO.

### Rooms

`_room_for_payload(payload)` decides the target room:

| Payload contains | Room |
|---|---|
| `lead_id` | `lead:<lead_id>` |
| `conversation_id` or `id` | `conv:<conversation_id>` |
| Neither | `None` — publishers must suppress, not broadcast |

Publishers must suppress unroutable events rather than treating `None`
as a broadcast room.

`_ConnectionAccess` is the per-SID record of authenticated identity
plus server-authorized rooms (`rooms`, `presence_entities`,
`typing_entities`). It is mutated by the `presence join` /
`presence leave` / `typing` handlers so a recruiter can only see
conversations / leads they are entitled to (via
`viewer_can_access_conversation` and `viewer_can_access_lead`).

### Presence and typing

`sio.on("presence join")` / `("presence leave")` register / deregister
a recruiter's view via `services.presence.join_viewing` /
`leave_viewing`. `sio.on("typing")` events are scoped to
`(entity_type, canonical_id)` and rate-limited so a noisy client cannot
flood the room.

## Bridge: `backend/app/realtime/emitter.py`

Any process that wants to publish — `worker-chatbot`, the web process,
the proactive tick — uses `emit_event(event_type, payload, room)`. The
module lazily builds an `AsyncRedisManager(write_only=True)`:

```python
def _get_manager() -> socketio.AsyncRedisManager:
    global _manager
    if _manager is None:
        _manager = socketio.AsyncRedisManager(settings.redis_url, write_only=True)
    return _manager
```

Three properties matter:

- **`write_only=True`** — the bridge never starts a local server, only
  publishes. Importing the bridge from `worker-chatbot` therefore
  carries no ASGI lifespan cost.
- **Best-effort emit.** `emit_event` swallows every exception and
  resets the manager on failure (`reset_manager`). Realtime must never
  break a write — a dropped event degrades the UI, a failed event that
  aborts a write loses candidate data.
- **Per-loop freshness.** The RQ worker uses `asyncio.run` per job
  (each job gets a fresh event loop). The manager is bound to a loop
  on first use; resetting it after any failure guarantees the next
  emit builds a fresh, loop-correct manager.

The reset pattern is the answer to the "event loop is closed" failure
mode that haunts async Redis clients in long-running workers.

## SSE fallback

The legacy SSE firehose (`/realtime/*`) is kept as a fallback for
environments where Socket.IO cannot be deployed (some restrictive
proxies strip the `Upgrade` header). Caddy routes `/realtime/*` to the
same `__WEB_UPSTREAM__:8000` with `flush_interval -1` so events flush
immediately instead of being held by the proxy buffer. The server-side
SSE handler reuses the same `services.realtime.publish_event` so the
two transports share event sourcing.

The console client prefers Socket.IO and only falls back to SSE when
the WebSocket upgrade fails.

## Event sourcing and the room contract

`services.realtime.publish_event(event_type, payload, room)` is the
single publishing seam. It routes:

- `conv:<id>` events to per-conversation rooms (every recruiter who has
  joined that conversation sees them).
- `lead:<id>` events to per-lead rooms (typically used by the lead
  kanban).
- Server-authorized rooms only — a recruiter who has not joined a
  conversation's presence receives the event when they next open it
  but does not get a push.

The recruiter console (`frontend/src/components/atomic-crm/providers/realtime/realtime-socket.ts`)
connects on mount, joins the rooms for any conversation currently in
view, and leaves on unmount. The runtime-generation reset (see
[`openwiki/frontend/recruitment-console.md`](../frontend/recruitment-console.md))
calls `closeRealtimeSocket()` so an authority bump never leaves a stale
socket attached to an old bundle.

## Why this shape

- **One publish seam.** Every state change funnels through
  `services.realtime.publish_event`, regardless of which process owns
  the mutation. The bridge handles transport.
- **Caddy stays simple.** `/webhooks`, `/api`, `/realtime`, `/socket.io`
  all proxy to the same web color. WebSocket upgrades are transparent.
- **Fail-soft push.** A dropped event degrades the UI; a successful
  write never depends on the realtime channel.
- **No loop-bound singletons in workers.** The reset-on-failure pattern
  survives the per-job event loop that `worker-chatbot` uses.
