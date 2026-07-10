---
title: "Graphite, Cloud, and Emerald UI Refactor"
date: "2026-07-11"
status: completed
scope: "Authenticated conversations, settings, and performance workspaces"
---

# Graphite, Cloud, and Emerald UI Refactor

## Context

The authenticated recruiter/admin workspace needed a calmer, more operational
visual system without changing data, routes, permissions, or realtime behavior.
The target was a graphite navigation shell, cool-neutral content canvas, and a
restrained emerald action system at desktop and mobile widths.

## What happened

- Simplified the conversation header: candidate details now open from the name
  in one full-width, scrollable mobile sheet; redundant quick-fact and takeover
  header controls were removed in favour of the mode control.
- Flattened menus and the candidate detail sheet by removing decorative depth
  while retaining visible focus, named controls, and the existing close path.
- Clarified settings actions: a connection check that persists pending values
  is labelled `Lưu & kiểm tra`.
- Made performance states honest: absent latency data shows an empty state,
  zero 429/fallback counts are healthy rather than warnings, and outcomes use
  Vietnamese labels.
- Marked the graphite/cloud token direction authoritative and the older
  warm-paper document superseded; code standards now state shared versus
  feature-scoped token ownership.

## Decisions

- Use graphite only for global navigation, cloud/white for workspace surfaces,
  and emerald only for selection, focus, primary actions, and healthy status.
  This contrast scope applies to the authenticated light workspace; login and
  the global dark theme remain unchanged.
- Prefer one progressive-disclosure path for candidate details over parallel
  header buttons, icon strips, and nested action menus.
- Do not imply latency or warning conditions when the underlying performance
  data is empty or zero.
- Preserve API, secret, permission, route, and responsive breakpoint contracts
  while refining presentation.

## Next

- Treat `docs/design-tokens-graphite-cloud.md` as the active visual direction;
  do not revive the superseded warm-paper palette in authenticated workspaces.
- Keep shared `--workspace-*` roles in `frontend/src/index.css`; add local
  aliases only when a feature has a genuine local surface need.
- Retain the verified gates for follow-up UI work: live authenticated mobile
  and desktop smoke checks, then frontend typecheck, lint, and production build.
