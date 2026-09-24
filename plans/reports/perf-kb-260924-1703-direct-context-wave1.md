# PERF-04 (app-code half) — direct-context lane: cached routing catalog + targeted text fetch

Ticket: `kanban/PERF-04-direct-context-lane-runs-an-uncached-full-KB-scan-every-turn-and.md` — app-code half only; the prompt shape/size half stays gated.

## Outcome

Every direct-context turn previously ran an uncached three-entity join that
shipped the `raw_text` + `normalized_text` TEXT columns of **every active
project** over the wire, then re-SELECTed the selected file row (both TEXT
columns again) inside the capacity guard. A turn now does one Redis version
read + one Redis get for the routing catalog, and only the selected project's
`normalized_text` is fetched — once, via a targeted `load_only` query — with the
capacity check running on that pre-fetched file. The whole-KB-as-prompt shape is
untouched.

## What changed

- `backend/app/graph/factories.py`
  - New `_DirectContextCatalogEntry` (plain data: project_id, slug, name,
    aliases, kb_id, mode) and `_load_direct_context_catalog()`: reads a JSON
    catalog from Redis under key `preamble:direct_context_catalog:v{version}`
    (existing `NS_PREAMBLE` namespace, existing `cache_version` /
    `cache_get_json` / `cache_set_json` helpers from `core/cache.py` — no new
    namespace scheme, `core/cache.py` untouched). On a miss it runs the old
    join minus the `KnowledgeBaseDirectFile` outerjoin — so no TEXT column is
    selected for any project — and writes the cache back (TTL 600 s).
  - `_DirectContextAdapter.resolve()` routes from the catalog entries with the
    identical slug/name/alias regex, order, EXPLORE/clarification branches,
    general/comparative guard (`len(entries) >= 2`), and focused-id fallback.
    For a selected DIRECT_CONTEXT project it fetches the file with
    `select(KnowledgeBaseDirectFile).options(load_only(KnowledgeBaseDirectFile.normalized_text))`
    — one row, one TEXT column, `raw_text` never leaves the DB — and passes the
    pre-fetched file to the capacity guard. Empty-file and RAG cases unchanged
    (`DirectContext(knowledge_text="")`, `direct_context=None`).
- `backend/app/services/knowledge_base_capacity.py`
  - New `ensure_direct_context_fits(db, direct_file, *, agent_markdown)` holds
    the fits-check + ConflictError. `require_direct_context_ready` keeps its
    signature and behavior for admin/persona callers (knowledge_base_service,
    personas/service) and now delegates to it. The per-turn lane no longer
    re-SELECTs the row; nothing accesses `raw_text` in the turn path.

## Cache/invalidation reasoning

The projection (slug/name/aliases/mode per active project) changes only on
admin writes that already bump `NS_PREAMBLE`: project create (`project/service.py:229`),
update incl. name/aliases/is_active (`:262`), delete (`:276`), single-page
activation (`:334`), plus index-card writes (`project_index_repository.py:53,85`).
The versioned key makes the bump the invalidation; the 600 s TTL only bounds a
missed bump. KB mode is immutable after KB creation (no update path sets
`mode`), and direct-file re-uploads (`upsert_direct_file`) correctly do **not**
invalidate the catalog because file content is not part of the routing
projection — the text is fetched fresh per turn. One known gap: `bootstrap_legacy`
attaches a legacy RAG project to a KB without bumping `preamble`, so a
newly-attached legacy project may be unroutable for up to 10 minutes (TTL
safety net); the next admin project save flushes it. Best-effort throughout: on
any Redis failure the DB query runs, and a corrupted cached payload falls
through to the DB and self-heals by re-writing the key.

## Deviation from the ticket's literal wording (deliberate)

The ticket suggested caching `estimated_input_tokens` alongside the file
checksum. That cache is unnecessary: `_estimate_tokens` is `ceil(len(text)/2)`
— an O(1) `len()` — and the selected file's text is in hand anyway (it is the
system prompt). The re-SELECT was the real cost (a second full transfer of both
TEXT columns), and that is gone: the guard runs on the already-fetched row. A
Redis entry for a value derivable in constant time from data already loaded
would have added a round-trip to save nothing. The ticket's stated goal —
"stop re-SELECTing the same row and re-tokenising the full text every turn" —
is met exactly.

## Test evidence

- Narrow first: `tests/test_graph_factories.py tests/test_graph_direct_context.py tests/test_knowledge_base_service.py` → 62 passed.
- Full unit lane: `pytest -m "not integration"` → **2279 passed, 42 skipped** (2243 baseline + teammates' concurrent additions + 5 new tests here).
- `.venv/bin/ruff check .` → All checks passed.

New tests: catalog cache hit serves routing with the DB refusing to execute;
cold path writes `preamble:direct_context_catalog:v{N}` with TTL 600 and the
exact entry payload; focused DIRECT_CONTEXT turn fetches the selected file
exactly once (`scalar_calls == 1`) and embeds its text; capacity module
fit/over-limit/missing-file/present-file paths.

## Gated half (not implemented — approval required)

The whole-KB-as-prompt shape/size (`build_direct_system` embedding the entire
normalized text as the system prompt, runner.py system-prompt injection) is a
prompt-policy change under the AGENTS.md approval gate and is flagged, not
changed. A near-term mitigation candidate lives behind that gate: the assembled
system prompt could ride the existing `cached_system_prompt` Redis cache, but
any prompt-shape change (e.g. truncation policy) needs maintainer sign-off.

## Unresolved questions

1. Should `bootstrap_legacy` bump `NS_PREAMBLE` (one line in a file I don't
   own)? Today a legacy-attached RAG project can lag the routing catalog by up
   to the 10-minute TTL.
2. If prompt-shape ever changes, `require_direct_context_ready` /
   `ensure_direct_context_fits` already return the `DirectContextCapacity`
   object the capacity endpoint needs, so the gated work can build on it.
