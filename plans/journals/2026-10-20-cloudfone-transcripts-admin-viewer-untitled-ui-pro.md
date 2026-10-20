---
title: Cloudfone transcripts admin viewer (Untitled UI Pro)
date: 2026-10-20
summary: Read-only list+detail API + UUI-table viewer page opened from Cloudfone settings; React Aria rows memoize per item so cells stay state-independent.
---

# Cloudfone transcripts admin viewer (Untitled UI Pro)

## What happened

- Ask: admin web viewer for stored CloudFone voice-call transcripts, designed with Untitled UI Pro, opened from a button in the Cloudfone settings page ("do it properly" via ak-agentkit).
- Untitled UI MCP (PRO access) → design locked on `settings-01/09` + `informational-02/03` anatomy (settings split-pane + filter bar + data table + pagination); per `frontend/AGENTS.md` the code uses the repo's vendored UUI v8 primitives (`components/application/table`, `pagination`, `kit/EmptyState`) — no second component layer.
- Shipped: `GET /admin/integrations/cloudfone/transcripts` (day + caller-fragment filters, pagination, 160-char preview) + `GET …/{call_id}` (full text, 404 `NotFoundError`); `CloudfoneTranscriptsSection` page with filter bar, table, pager, detail panel; "Xem bản ghi cuộc gọi" button in the Cloudfone section; console wiring (hidden non-rail view + own header copy).
- Route oracle updated with dated delta (`integrations: 42→44`); deployment-guide Alembic HEAD repaired to `0076` (the previous release bypassed `release-check`, leaving documented drift).
- Verification: 4083 backend + 1048 frontend unit green; 4 API contract + 3 real-DB query tests; wired Playwright e2e (real console + real API) green with a reviewed screenshot.

## Decision

- Row cells hold NO selection state: React Aria table rows memoize per item, so state-dependent cell content renders stale (empirically confirmed — two attempts at collection invalidation failed). The open/close lifecycle lives in the detail panel below the table; the row action is a plain "Xem".
- List/detail split keeps table payloads light and matches the viewer's read pattern (scan many, read one fully).

## Next steps

- PII retention/TTL decision for `cloudfone_call_transcripts` (still with the data owner).
- If transcripts start filling pages with long text, add server-side transcript search (`transcript` column) behind the same filter bar.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
