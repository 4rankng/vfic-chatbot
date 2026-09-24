---
id: FE-10
title: "A module-scope socket port pulls socket.io-client into the entry chunk and never re-auths after JWT rotation"
severity: medium
area: frontend
labels: [performance, reliability]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# FE-10 — A module-scope socket port pulls socket.io-client into the entry chunk and never re-auths after JWT rotation

**Severity:** medium · **Area:** frontend · **Effort:** S · **Labels:** performance, reliability

**Trạng thái:** DEV_COMPLETED

## Problem

`createLeadRealtimePort(getRealtimeSocket())` is evaluated at module scope in a file that the entry graph imports eagerly, so the `realtime-vendor` chunk is fetched on first paint even though the port is only needed inside the inbox. The same socket also reads the JWT only when a connection attempt starts, so a long-lived socket keeps its original token after a mid-session refresh.

## Evidence

- `frontend/src/components/atomic-crm/capabilities/recruitment/index.tsx:32` — `const leadRealtimePort = createLeadRealtimePort(getRealtimeSocket());` at module scope, evaluating at import time before any conversation is opened.
- `frontend/src/components/atomic-crm/providers/realtime/realtime-socket.ts:21-33` — `getRealtimeSocket()` constructs the Manager even with `autoConnect` false, so the module graph determines the chunk.
- `frontend/src/components/atomic-crm/capabilities/recruitment/index.tsx` is imported eagerly via `capabilities/static-recruitment-runtime.ts:1-2` → `root/reset-runtime-state.ts:6-10` → `App.tsx:6`/`installation/InstallationBootstrap.tsx`, so `vite.config.ts`'s `realtime-vendor` split does not keep socket.io-client off first paint.
- `frontend/src/components/atomic-crm/providers/realtime/realtime-socket.ts:23-25` — the JWT is read in the socket `auth` callback only when a connection attempt starts, while `lib/apiClient.ts:161-176` (`refreshOnce()`) rotates the token. [INFERRED — the backend's re-authorisation of an already-open socket was not verified.]
- Teardown on logout is correct: `providers/rest/authProvider.ts:97-102` calls `closeRealtimeSocket()`.

## Impact

Entry-bundle bytes are spent on a library only needed inside the inbox, plus a silent "no realtime after token rotation" failure mode whose symptom (missing lead updates) is indistinguishable from a backend bug.

## Suggested fix

Convert `leadRealtimePort` into a lazily-created getter inside `RecruitmentConversationContext`, and lazy-load `Dashboard` (which already owns the only `react-virtuoso` usage). For the token, emit a socket re-auth (`socket.disconnect().connect()` or an `auth.refresh` event) when `refreshOnce()` succeeds.

## Evidence log

- 8be895b6 — the module-scope `createLeadRealtimePort(getRealtimeSocket())` became a lazy, socket-memoized getter, so socket.io-client is no longer constructed at import and its chunk is not fetched on first paint.
- `apiClient` gained an `onAccessTokenRotated` seam and the socket re-handshakes on it, so a long-lived connection re-presents a rotated JWT instead of silently going dead.
- Fixed a pre-existing bug found on the way: `leadRealtime` did not re-emit `join lead` on reconnect, so `lead.updated` silently stopped after any network blip. It now rejoins through one shared `join()` helper.
- Verified by mutation: re-adding the module-scope construction fails the suite at import with a thrown sentinel; the re-auth test reproduces the real library's auth-callback contract.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
