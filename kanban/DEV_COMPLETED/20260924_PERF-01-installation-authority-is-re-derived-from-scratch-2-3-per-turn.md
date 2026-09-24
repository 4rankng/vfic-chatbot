---
id: PERF-01
title: "Installation authority is re-derived from scratch 2–3× per turn"
severity: high
area: performance
labels: [performance, reliability]
effort: M
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# PERF-01 — Installation authority is re-derived from scratch 2–3× per turn

**Severity:** high · **Area:** performance · **Effort:** M · **Labels:** performance, reliability

**Trạng thái:** DEV_COMPLETED

## Problem

`resolve_active()` runs the full authority derivation — state, revision, manifest validation, template checksums, configured integrations, persona version, case workflow version, active KB vector — and only then consults the fingerprint cache, so the cache short-circuits the final assembly rather than the queries. The graph then calls it 2–3× per turn plus once per inbound webhook.

## Evidence

- `backend/app/services/installation/service.py:523` — `resolve_active()` runs `get_state()` → `get_revision()` → `db.get(InstallationManifestValidation)` → `_validation_is_current(...)` → `active_kb_vector()` → `_active_context(...)`, and only at `:560` consults `get_cached_fingerprint`.
- `backend/app/services/installation/service.py:797-864` — `_validation_is_current` adds `template_checksums` and `configured_integrations` SELECTs plus `get_persona_version` and `db.get(CaseWorkflowVersion)`; the `select()` statements hit the DB even on a warm session (only `db.get` benefits from the identity map).
- `backend/app/graph/runner.py:1162` — `runtime_stamp_is_current`; `:1188` and `:1202` — `resolve_active_policy`; `:580` — `_authority_gate` reaches `resolve_active_policy` on its short-circuit paths.
- `backend/app/api/webhooks.py:57` — `_runtime_authority_or_inactive` pays the same derivation once per inbound webhook; `backend/app/composition/conversation_messaging.py:40` does so on the inline web-chat path.

## Impact

~11–13 DB round trips and 4–6 Redis GETs per turn [EST] — roughly 25–35% of all turn queries — all serial and all before the LLM starts. On a 2 vCPU box sharing one Postgres this consumes most of `sla_seconds=10` and `soft_fallback_remaining=2.0`, the FAQ and side-lookup budgets the deadline logic depends on.

## Suggested fix

Make it cache-first and resolve once per turn: (a) have `resolve_active()` read `get_cached_fingerprint` — or a new lightweight `installation_state.authority_generation + active_revision_id` read, one query — before the full derivation, paying the validation path only when the version/identity changed or the cache entry is absent; (b) compute it once in `run_turn` and pass the resolved policy into both the stamp check and `_authority_gate` via a per-turn memo on `BotRunState`/`GraphDeps`; (c) keep `invalidate_installation_cache()` (`service.py:922`, bumped on activate/resume/rollback) as the correctness gate so a cutover is still observed on the next turn. A too-sticky memo could serve authority one turn too long, so bound it with the version counter plus a short TTL.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
