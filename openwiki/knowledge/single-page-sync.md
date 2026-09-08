---
type: "Reference"
title: "Single page sync"
openwiki_generated: true
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
---


The single-page external source sync is the path that turns one public
Google Sheet into the **direct-context** file attached to a `DIRECT_CONTEXT`
knowledge base. It runs on its own model
(`single_page_external_source_sync_state`, migration 0053) so the
behaviour stays additive to the broader RAG-category sync path
(`external_source_sync_state`, migration 0052). The shape mirrors
`ExternalSourceSyncState` closely so operational handling — status,
retries, auto-disable — stays familiar.

## Single-gid constraint

Each row tracks one `(project, source)` pair and pins exactly one
`sheet_gid` (`BigInteger`, non-null). The `sheet_url` is validated
against a host allow-list at the API entry; the SSRF gate
reconstructs the export URL from the parsed sheet id at fetch time so
a stored URL is never trusted blindly.

`auto_sync_enabled` is per-row; there is no global kill switch. The
daily re-ingest cadence is pinned to a wall-clock time via
`Settings.kb_sync_cron` (a cron string) registered through
`register_unique_cron_tick` in `app/main.py` lifespan — a web-container
restart mid-day no longer pushes the next sync out by 24 hours.

## Triggers

Two triggers share the same code path (`sync_single_page_external_source`):

| Trigger | Path |
|---|---|
| **Manual "Xử lý ngay"** | Admin clicks the button on a single-page project; the API calls `sync_single_page_external_source` directly. |
| **Daily cron** | `run_single_page_external_source_sync_tick` runs on `kb_sync_cron`; it selects every row where `auto_sync_enabled` and enqueues one RQ job per row with a deterministic `job_id=f"single-page-ext-src-sync-{state_id}-{today}"`. |

The deterministic job id makes the daily re-enqueue idempotent: a
replay of the same tick cannot double-fire.

## Sync flow

`backend/app/services/project/single_page_external_sources.py:sync_single_page_external_source`
acquires a Redis lock keyed `single_page_ext_sync:{state_id}` with a
random owner token, then calls `_sync_locked`:

1. **Validate the project.** `_require_direct_context_project` raises
   `NotFoundError` / `ConflictError` if the project is missing or not
   single-page. On failure, `_mark_failed(state, code)` records the
   `last_error` and returns `status="FAILED"`.
2. **Fetch + render.** `SheetClient().fetch_csv(state.sheet_url,
   state.sheet_gid, max_bytes=SINGLE_PAGE_SHEET_MAX_BYTES)` downloads
   the CSV. `render_sheet_markdown(csv_text)` is **deterministic** —
   the same CSV bytes always produce the same Markdown. `csv.Error` →
   `parse_failed:csv_field_too_large`; other parse failures →
   `sheet_parse_failed`.
3. **Validate the body.** `DirectContextFileUpsert(filename, text=markdown)`
   runs Pydantic validation. Failure →
   `direct_file_rejected:content_too_large`.
4. **Hash-gated no-op.** `canonical_direct_file_stats(body.text)`
   produces the canonical `content_sha256`. If the existing file's
   hash matches, the sync writes `_mark_noop(...)`, optionally
   activates the project, bumps the preamble cache version, and
   returns `status="NO_OP"`. The operator's daily tick costs one CSV
   fetch + one hash compare.
5. **Apply under a nested transaction.** `db.begin_nested()` wraps
   `KnowledgeBaseService.upsert_direct_file(...)` plus, on activation,
   `_stage_project_activation`. The nested transaction exists so a
   caught exception only rolls back the diff — the prior page is
   preserved on any caught failure (`code = "direct_file_update_failed"`).
6. **Mark OK.** `_mark_ok(state, content_sha256, row_count)`.
7. **Index for cross-project retrieval.** When `markdown` is non-empty,
   `_enqueue_direct_context_index(knowledge_base.id, project.id,
   markdown)` stages a `direct_context` chunk into `knowledge_chunks`
   so the sheet-synced content participates in `search_knowledge` from
   other projects' turns — mirroring the admin-UI publish path. The
   enqueue is best-effort (Redis errors are swallowed) so a transient
   queue failure never rolls back this sync.
8. **Activate / bump.** On activation, `bump_cache_version(NS_PREAMBLE)`
   invalidates the system-prompt cache.

The Redis lock is released in a `finally` block via a Lua script that
checks the owner token before deleting, so a crashed predecessor's lock
does not get torn down by the next attempt.

## Status model

`SinglePageExternalSourceSyncOutcome.status` carries one of:

| Status | Meaning |
|---|---|
| `OK` | New content applied; new hash + row count recorded. |
| `NO_OP` | Hash matched; nothing changed. |
| `FAILED` | A typed error code is recorded on `last_error` (e.g. `project_invalid`, `parse_failed:csv_field_too_large`, `direct_file_rejected:content_too_large`, `direct_file_update_failed`, `no_sync_actor`). |
| `LOCKED` | Another sync holds the Redis lock. The worker re-raises so RQ retries after the lock TTL. |

The worker module increments one of two Redis counters per outcome
(`single_page_external_source_sync_success_total` /
`single_page_external_source_sync_failure_total`, 7-day TTL).

## Failure preserves prior state

The nested transaction + outer-state-update pattern is the invariant
that makes this contract safe:

- **Before** the upsert, the previous Markdown is in place on the
  `knowledge_base_direct_file` row.
- **After** the upsert commits, the new Markdown replaces it.
- **On caught failure**, the nested transaction rolls back so the row
  keeps its prior text. The state row records `last_status="FAILED"`
  + `last_error=<code>` + `consecutive_failures += 1`, and the live
  page is untouched.
- **On uncalled-for exception** (anything not caught), the outer
  `try/finally` still releases the lock, and the sync is treated as
  crashed. The next tick retries it; the lock TTL protects against
  pile-up.

The `direct_file_update_failed` branch logs `state.id`, the error code,
and the exception type but never the Markdown body or the row content —
secret/PII redaction is structural here as elsewhere.

## Consecutive failure auto-disable

`consecutive_failures` is incremented on each `FAILED` outcome. The
operator UI surfaces this; an admin can manually set
`auto_sync_enabled=false` to silence a misbehaving source without
deleting the row.

## What the worker does not do

- **No LLM call.** The sheet is rendered deterministically — there is
  no chunking decision that an LLM could second-guess.
- **No cross-sheet fan-out.** One row → one gid → one Markdown file.
  Multiple sources per project use multiple rows.
- **No direct DB writes outside the lock.** The whole sync runs under
  one Redis lock so two workers cannot race on the same row.

## Operator workflow

```text
admin creates a DIRECT_CONTEXT project (or activates an existing one)
admin attaches the public Google Sheet URL + gid → auto_sync_enabled=true
admin clicks "Xử lý ngay" or waits for kb_sync_cron
worker fetches the sheet → renders Markdown → upserts the file
chunks staged to knowledge_chunks via _enqueue_direct_context_index
next turn sees the updated system prompt (cache version bumped on activation)
```

If a sheet change happens mid-day and the operator wants it live
immediately, "Xử lý ngay" runs the same code path as the cron — no
special-case logic.
