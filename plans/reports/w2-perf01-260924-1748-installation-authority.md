# PERF-01 — installation authority is re-derived from scratch 2–3× per turn

Date: 2026-09-24 · Branch: main · Commits: `b3622d2d`, `3050b76c`, `601027aa`

## Outcome

Installation authority is now resolved cache-first and exactly once per turn, per
the ticket's fix (a)+(b)+(c). A warm turn path pays 3 DB queries + 2 Redis GETs
per resolution (state row, revision PK, KB-vector join; namespace version +
fingerprint payload) instead of the full ~11–13 DB round trips + 4–6 Redis GETs,
and `run_turn` derives it once instead of twice. Webhook and inline web-chat
ingress (one `resolve_active` per inbound) get the same cache-first path
automatically through `InstallationService`.

### (a) Cache-first `resolve_active` — `app/services/installation/service.py`

`resolve_active()` now reads `get_cached_fingerprint(active_revision_id,
authority_generation)` immediately after the lifecycle guard. On a hit it still
confirms the three things that must stay DB-backed — the revision row, the
registry pack contract (`_registry_pack_current`, extracted from the duplicated
inline check), and the live KB vector — then serves the cached fingerprint
without running `_validation_is_current`. The KB-vector compare is deliberate:
KB publishes bump the `knowledge`/`semantic_cache` namespaces
(`bump_kb_caches`) but not `installation_authority`, so the vector is the one
fingerprint input that moves on a routine operation; serving it TTL-bounded
would delay outbox stamp-fencing after every publish. One small join keeps that
exact. The old tail (derive `expected`, re-read the cache, compare checksums)
is gone — it was a second cache read that could only confirm what the top-of-
function read already decided. On a miss the full derivation runs unchanged and
re-warms the cache via `_active_context`.

Composition with today's `cache.py` (a23033a1): nothing here calls
`cache_version` directly. A seeded fresh generation simply produces a key miss
→ full derivation → write under the seeded version; no stale `v{n}` entry can
be resurrected through this path.

### (b) Once per turn — `app/graph/runner.py`

`run_turn` no longer calls `runtime_stamp_is_current` and then
`resolve_active_policy` (two full derivations). It resolves the policy once and
compares the turn's stamp against the resolved policy: `revision_id` equality
plus `fingerprint_checksum` equality. The checksum covers the complete
canonical payload — including `authority_generation` and the KB vector — so
checksum equality subsumes the stamp-currency check (a generation bump or
rollback changes the checksum even when manifest content is identical; pinned
by `test_generation_change_invalidates_fingerprint_even_after_revision_rollback`).

No `BotRunState`/`GraphDeps` memo field was added: the once-resolved policy is
a `run_turn` local whose lifetime is exactly the turn, which achieves the
ticket's "resolve once, bound with version counter + short TTL" guarantee
without a TTL-bounded memo object at all. `graph/state.py`-equivalent
(`graph/types.py`) is untouched.

### (c) Correctness gate unchanged

`invalidate_installation_cache()` still fires on create/validate/activate/
rollback/suspend/resume, and every lifecycle mutation also advances
`authority_generation`, so a cutover is observed on the next turn: the read key
(namespace version + revision + generation) misses and the full derivation
re-runs. Pinned by the rewritten integration test below.

## Accepted trades (per the ticket)

- Validation-internals drift on a warm hit — a required integration setting
  disabled, template/workflow status flips — is now TTL-bounded at 600s
  instead of observed next turn. Lifecycle cutovers are not affected (see (c)).
- Reason-label merge: a stamped turn whose policy cannot be resolved now always
  stands down as `stale_runtime_authority`. The old `missing_runtime_policy`
  branch was unreachable (the stamp check fired first whenever
  `runtime_policy` was None) and is folded in; the rare
  persona-body-missing-with-current-stamp case, previously
  `inactive_runtime_policy`, now also reports `stale_runtime_authority`.
  Nothing in backend or frontend references the removed labels (grep clean).
- `runtime_stamp_is_current` remains on the service and the port (outbox uses
  the service method directly); `run_turn` just no longer calls the port one.

## Test evidence

- `tests/integration/test_installation_lifecycle.py` — 5 passed (local
  Postgres). The forged-cache assertion in the lifecycle mega-test was
  rewritten for the new contract (identity-scoped forge: a hit for the exact
  current identity is served; advanced generations re-derive), and a new test
  `test_resolve_active_serves_a_warm_hit_without_revalidating_and_rederives_on_cutover`
  pins both sides: warm hit served with `_validation_is_current` never called
  (0 invocations), cutover to a second revision re-derives from the database.
- `tests/test_runtime_policy_composition.py` + `tests/test_graph_runner_turn.py`
  — 105 passed. The stale-turn fake now stubs `resolve_active_policy` (the port
  method `run_turn` actually calls); new
  `test_stamped_turn_compares_the_stamp_against_one_policy_resolution` pins
  one resolution per stamped turn with a mismatched fingerprint.
- Adjacent authority-path suites (`test_web_chat_endpoint`, `test_webhooks`,
  `test_direct_turns`, `test_graph_proactive_turn`, `test_persistence_worker`,
  `test_channel_contracts`, `test_generic_api_guards`, `test_access_policies`,
  `test_runtime_authority_stamps`) — 110 passed, then 184 passed across the
  combined final re-run.
- Full lane `.venv/bin/pytest -m "not integration"`: **2465 passed, 3 failed,
  42 skipped**. All three failures are the concurrent session's, none touch my
  files, verified with a detached clean checkout of HEAD (which includes my
  commits):
  - `test_no_new_layer_boundary_violations` and
    `test_frontend_domain_and_application_layers_do_not_use_browser_io_globals`
    fail at clean committed HEAD too — excess edges are exclusively
    `frontend/src/components/atomic-crm/**` files from the concurrent
    session's landed frontend commits (FE-13 moves); zero backend edges.
  - `test_broad_side_effect_scan_matches_reviewed_boundary_snapshot`
    (`provider_boundary` 123 vs 122) **passes** at clean HEAD and fails only
    in the live tree — the delta is the other session's uncommitted
    `app/graph/clients.py` prompt-caching edit (a provider-transport file).
- `.venv/bin/ruff check .` — clean.

No push, no branches, no stash; commits added by explicit path only
(`app/services/installation/service.py`, `app/graph/runner.py`, and the two
test files). The concurrent session's dirty files were never staged.

## Deferred

Nothing deferred. One attribution-worktree was created and removed during
failure analysis (`git worktree remove --force`, pruned).

Status: DONE
Summary: Installation authority resolves cache-first (warm hit = 3 DB + 2 Redis,
was ~11–13 DB + 4–6 Redis) and once per turn in `run_turn` (was twice), with
`invalidate_installation_cache()` still fencing cutovers next turn; 2465 unit
tests pass and the 3 lane failures are precisely attributed to the concurrent
session's frontend commits and uncommitted `clients.py`.
Concerns: None blocking. The TTL-bounded validation drift (600s) and the
`stale_runtime_authority` label merge are the ticket's accepted trades,
documented above and in the commit messages.
