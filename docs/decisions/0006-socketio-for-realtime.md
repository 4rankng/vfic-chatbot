# ADR-0006: Socket.IO Over SSE for Realtime Communication

- **Status:** Accepted
- **Date:** 2026-06-28
- **Decider:** Project lead

## Context

The recruiter console needs realtime updates for:
- New incoming messages from candidates (Zalo → bot → console).
- Bot reply status (thinking, sent, suppressed).
- Presence (which recruiter is viewing which conversation).
- Typing indicators.

The backend runs behind Caddy (HTTP reverse proxy) on a 2 vCPU droplet. Workers (RQ) generate events that must reach the browser.

Options considered: Server-Sent Events (SSE), WebSocket (raw), Socket.IO.

## Decision

Use **Socket.IO** (`python-socketio>=5.11` server, `socket.io-client` frontend) with `AsyncRedisManager` for cross-process pub/sub.

Key reasons:
- **Bidirectional.** The console needs to both receive events (new messages) and send events (join conversation, typing). SSE is server→client only; Socket.IO is bidirectional.
- **Rooms.** Socket.IO's room system maps perfectly to per-conversation and per-lead subscriptions: `conv:{conversation_id}`, `lead:{lead_id}`, `user:{user_id}`.
- **Presence.** Built-in connect/disconnect events enable presence tracking (`presence join`, `presence leave`, `presence heartbeat`).
- **Cross-process pub/sub.** `AsyncRedisManager` lets RQ workers emit events to browser sockets via Redis pub/sub — the worker doesn't hold the WebSocket connection.
- **Auto-reconnect with gap-fill.** Socket.IO client auto-reconnects; `useConversationRealtime.ts` fetches missed messages via `getMessagesSince()` on reconnect.
- **WebSocket with polling fallback.** Socket.IO upgrades from polling to WebSocket automatically — works behind Caddy without special config.

## Consequences

- **Positive:** Rich event model (rooms, presence, typing). Cross-process emit via Redis. Standard client library with auto-reconnect.
- **Negative:** Socket.IO protocol adds overhead vs. raw WebSocket. The `AsyncRedisManager` means every emit goes through Redis (minor latency). Legacy SSE endpoint (`/realtime/events`) still exists in `api/realtime.py` — should eventually be removed.
- **Neutral:** Socket.IO server is mounted as `socketio.ASGIApp(sio, other_asgi_app=fastapi_app)` in `main.py` — Socket.IO serves at `/socket.io/`, FastAPI handles everything else. Auth via JWT in handshake `auth.token` or Bearer header.

## Related

- Server: `backend/app/realtime/socketio.py` (connect, rooms, presence)
- Emit bridge: `backend/app/realtime/emitter.py` (write-only, for RQ workers)
- Mount: `backend/app/main.py` (ASGIApp)
- Client: `frontend/src/lib/vfic/realtimeSocket.ts` (singleton, lazy connect)
- Usage: `frontend/src/components/atomic-crm/conversations/chatRepository.ts` (`subscribeToMessages`)
- [docs/system-architecture.md](../system-architecture.md) §8 (Realtime)
