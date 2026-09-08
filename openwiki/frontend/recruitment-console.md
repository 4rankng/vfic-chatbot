---
type: frontend
title: Frontend architecture and the atomic-crm recruitment console
description: Three-layer dependency direction (atomic-crm → admin → ui), bootstrap and PWA service worker, runtime generation reset on authority bumps, and how the console is wired to the FastAPI backend.
tags: [frontend, atomic-crm, shadcn-admin-kit, pwa, runtime-generation, vite]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
sources:
  - id: openwiki-source-454c9bcdde0b77b35e0fc994
    resource: repo://frontend/src/App.tsx
  - id: openwiki-source-f815c9b954867fc7c0e8385c
    resource: repo://frontend/src/components/atomic-crm/capabilities/static-recruitment-runtime.ts
  - id: openwiki-source-75c2181c4dd678aa0e72df18
    resource: repo://frontend/src/components/atomic-crm/conversations/infrastructure/runtime-epoch-adapter.ts
  - id: openwiki-source-2556b75c6810888c9da3e32b
    resource: repo://frontend/src/components/atomic-crm/conversations/reset-runtime.ts
  - id: openwiki-source-472e308be87e0efe4fb4c277
    resource: repo://frontend/src/components/atomic-crm/providers/commons/canAccess.ts
  - id: openwiki-source-b3d078ef416880590e4d2399
    resource: repo://frontend/src/components/atomic-crm/root/reset-runtime-state.ts
  - id: openwiki-source-4622f09188c7b2fdc738352b
    resource: repo://frontend/src/main.tsx
  - id: openwiki-source-378e3cf05ab0d05d335c68d5
    resource: repo://frontend/vite.config.ts
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
---

The frontend is a **React Admin SPA** built on the `atomic-crm` template,
layered over a vendored `shadcn-admin-kit` (`admin/`) and the shadcn
primitives (`ui/`). The dependency direction is strict:

```text
atomic-crm  →  admin  →  ui
(product)     (kit)     (primitives)
```

All product code lives in `atomic-crm/`; the other two layers are
vendored, mutable dependencies that the product code consumes. A new
product module belongs under `atomic-crm/<domain>/`, never under
`admin/` or `ui/`. This rule keeps the kit pristine and lets future
upstream patches roll in cleanly.

## Bootstrap

`frontend/src/main.tsx`:

1. Registers the **PWA service worker** with `registerSW({ immediate: true })`
   using `vite-plugin-pwa`'s Workbox registration. In `autoUpdate` mode,
   a new SW takes control and reloads an open tab — so a deployed UI
   cannot keep running an old application bundle until the recruiter
   notices.
2. Installs a `vite:preloadError` listener that calls `window.location.reload()`
   once, gated by a `sessionStorage("chunk-reload")` flag. After a deploy,
   the SW may replace its pre-cache while the page still holds old chunk
   references; a reload picks up the new HTML + SW cache, and the
   sessionStorage guard prevents an infinite reload loop. The comment
   cites Vite's `load-error-handling` docs.
3. Renders `<InstallationBootstrap><App /></InstallationBootstrap>`
   inside `StrictMode`.

`InstallationBootstrap` resolves the current installation manifest
(active vs. needs-install) and exposes it via `useInstallationContext`.
The manifest's `authority_generation` is the runtime generation number —
bumped on every persona / project / knowledge edit — that drives the
runtime-generation reset (see below).

## App.tsx — runtime generation reset

`frontend/src/App.tsx` is intentionally tiny:

```tsx
const App = () => {
  const { manifest } = useInstallationContext();
  return (
    <ReadyRecruitmentApplication
      key={manifest.authority_generation}
      authorityGeneration={manifest.authority_generation}
    />
  );
};
```

`ReadyRecruitmentApplication` calls `ensureRuntimeGeneration(authorityGeneration)`
on mount and whenever `authorityGeneration` changes (driven by React's
`useEffect([authorityGeneration])`). On failure it shows a Vietnamese
recovery card with a single "Tải lại trang" (reload) button. The
`key={manifest.authority_generation}` prop on the outer wrapper forces
React to unmount and remount the whole subtree on every authority bump,
which triggers the reset path inside `ensureRuntimeGeneration`.

## Runtime generation reset

`frontend/src/components/atomic-crm/root/reset-runtime-state.ts`
owns the reset machinery. A `RuntimeGenerationBundle` is the per-
generation singleton built by
`static-recruitment-runtime.ts:getStaticRecruitmentRuntimeKey(authorityGeneration)`,
which returns `recruitment:${authorityGeneration}`.

`ensureRuntimeGeneration(authorityGeneration)`:

1. Computes the requested key from the current `authorityGeneration`.
2. If a bundle is already active and the key matches, returns it
   immediately.
3. Otherwise calls `resetActiveRuntimeState()` which:
   - Closes the realtime socket
     (`closeRealtimeSocket()` from
     `providers/realtime/realtime-socket`).
   - Increments `runtimeEpoch` and resets the conversation runtime
     state via `resetConversationRuntimeState()`.
   - Cancels in-flight queries, clears the query and mutation caches,
     calls `previous.store.teardown()`.
   - Clears `LEGACY_ADAPTER_KEYS` from `localStorage`:
     `vfic:chatops:saved-views:v1`, `vfic:chatops:active-filter:v1`,
     `vfic:chatops:recent-tags:v1`, `app.configuration`.
4. Builds a fresh `QueryClient` (`offlineFirst` network mode, 30 s
   `staleTime`, 24 h `gcTime`) and a fresh `ra-core` store, keyed by a
   deterministic FNV-1a hash of the runtime key
   (`CRM:<hex>`).

`runtimeEpoch` is exposed via `getRuntimeEpoch()` /
`isRuntimeEpochCurrent()` and bound into the conversation runtime
through `bindConversationRuntimeEpoch({ capture, isCurrent })` so async
conversation work can abort itself when the generation moves.

`clearActiveDecisionTraceQueries()` lets the parent clear decision-trace
queries without holding a reference to the bundle (used when the user
navigates away from the bot-runs view).

## Vite and PWA configuration

`frontend/vite.config.ts` pins:

- `BACKEND_PORT` env (defaults to `8000`, tracks `make dev`'s
  `BACKEND_PORT`) for the dev-server proxy.
- `ANALYZE=true` opens `rollup-plugin-visualizer` (`./dist/stats.html`).
- `VitePWA({ registerType: "autoUpdate", workbox: { ... } })` with
  `cleanupOutdatedCaches: true` and explicit `globIgnores` for files
  that should not be pre-cached (favicons, logos, the Zalo verifier
  HTML, auth callback, etc.).

## Capability mirror

`frontend/src/components/atomic-crm/providers/commons/canAccess.ts`
mirrors the backend RBAC as a UX-only filter (see
[`openwiki/access/rbac-and-capabilities.md`](../access/rbac-and-capabilities.md)).
The file's own comment is explicit: **"Real enforcement is the FastAPI
backend (`app/api/dependencies.py`); this is the UX layer."** The
console never relies on the client gate to keep secrets off-screen.

## Realtime client

The console's realtime client (`providers/realtime/realtime-socket`)
connects to the per-conversation rooms exposed by the backend Socket.IO
server. It is closed by `closeRealtimeSocket()` as part of the runtime-
generation reset so an authority bump cannot leave a stale socket
attached to an old bundle. See
[`openwiki/messaging/realtime-socketio.md`](../messaging/realtime-socketio.md)
for the cross-process bridge contract.

## Why the reset exists

- The persona, projects, and knowledge base are runtime inputs to the
  static recruitment bundle. A change in authority_generation signals
  that the inputs moved; without a reset, the console would keep
  rendering the stale bundle until a hard refresh.
- `key={manifest.authority_generation}` is the React-level cue; the
  inner `ensureRuntimeGeneration` is the per-key state reset that clears
  the query client, the ra-core store, the realtime socket, and the
  legacy adapter keys.
- The Vietnamese recovery card on failure avoids an infinite spinner
  when the bundle cannot be built. The user gets one explicit action —
  reload — which is the only correct response.

## Where product code goes

- New domain: `frontend/src/components/atomic-crm/<domain>/`.
- New shared UI: extend an existing `atomic-crm/components/` module;
  never add to `ui/` (vendored) or `admin/` (vendored kit).
- The `atomic-crm` directory is the only layer the team edits; the
  `admin/` and `ui/` directories roll with their upstream packages and
  are mutated only when the package itself needs patching.
