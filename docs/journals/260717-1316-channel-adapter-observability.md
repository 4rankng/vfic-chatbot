---
date: 2026-07-17
session: channel-adapter-observability
---

# Journal: 2026-07-17 — Channel adapter observability

## Context

Zalo OA conversations appeared slower than Zalo Chatbot conversations, but the
system could not consistently separate bot execution time from adapter/provider
delivery time. We needed comparable operational evidence now and a contract
that future Facebook, Telegram, WhatsApp, or other adapters can adopt.

## What Happened

- Added the shared `OutboundTelemetry` contract for Zalo Bot and Zalo OA:
  adapter preparation, provider request, attempts, retries, refreshes, chunks,
  and final result.
- Persisted normalized adapter timing in `BotRun.stage_timings` for normal
  dispatch and outbox-recovery dispatch. Recovery creates a minimal BotRun when
  a crash occurred before one existed; it records adapter timing without
  inventing an inbound-to-send duration.
- Added performance API adapter aggregates and dashboard p50/p95 comparisons
  for provider and end-to-end timing, retry, and refresh counts.
- Kept outbound behavior unchanged: OA sends no typing indicator, progress
  acknowledgement, or extra message.

## Reflection

The crucial boundary is the adapter contract rather than a Zalo-specific report:
every channel can expose the same delivery measurements, while UI presentation
and message semantics remain channel-owned. Preserving telemetry through
recovery avoids a misleading observability gap precisely when delivery needs
the most investigation.

## Decisions Made

| Decision | Rationale | Impact |
|---|---|---|
| Use one adapter-neutral telemetry value | Makes comparisons and future adapter support consistent | Each adapter can emit the same normalized delivery stages |
| Record recovery delivery separately | A recovered send has no reliable original bot execution timestamp | Adapter timing remains accurate without fabricated E2E latency |
| Do not add OA progress messages | Explicit product constraint | No additional user-visible OA message is sent |

## Verification and scope

- Backend: `.venv/bin/ruff check . && .venv/bin/pytest -m 'not integration' --tb=short` — 1292 passed, 19 skipped, 21 deselected.
- Frontend: `npm run lint && npm run typecheck && npm run test:unit:app && npm run build` — 338 unit tests passed and production build succeeded.
- `git diff --check` passed.
- No migration, deployment, commit, or push was performed.

## Next Steps

- Use the new adapter comparison to validate the production latency hypothesis over a representative window.
- Have new channel adapters emit `OutboundTelemetry` at their provider boundary.
