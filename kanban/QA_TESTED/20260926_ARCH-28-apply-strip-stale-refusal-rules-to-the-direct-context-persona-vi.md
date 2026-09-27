---
id: ARCH-28
title: "Apply _strip_stale_refusal_rules to the direct-context persona via one shared resolver"
severity: medium
area: architecture
labels: [prompts, drift, duplication]
effort: S
status: done
column: QA_TESTED
opened: 2026-09-26
---

# ARCH-28 — Apply _strip_stale_refusal_rules to the direct-context persona via one shared resolver

**Severity:** medium · **Area:** architecture · **Effort:** S · **Labels:** prompts, drift, duplication

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

Persona resolution exists in two places with different behavior: the agent lane fetches the DB persona and strips stale privacy/refusal lines (_strip_stale_refusal_rules) before use, while the direct-context lane uses the raw PersonaRepository.active_persona_body with no strip — and the manifest lane composes policy.persona_body unstripped too. A DB persona still carrying the stale refusal rules therefore makes the bot refuse/hedge on focused-project turns while the same persona behaves correctly on agent turns. build_system_prompt even strips twice (resolve_persona strips, then the caller strips again) — the invariant has no single owner.

## Evidence

- backend/app/graph/context.py:56-76 — _strip_stale_refusal_rules + resolve_persona strip the DB persona before returning it
- backend/app/graph/context.py:135-146 — build_system_prompt's _assemble applies `_strip_stale_refusal_rules(await resolve_persona(…))` — a second strip of already-stripped text — and the error fallback strips AGENT_SYSTEM_PROMPT again
- backend/app/graph/adapters.py:286-287 — direct-context lane: `(await PersonaRepository(self._db).active_persona_body(provider)) or AGENT_SYSTEM_PROMPT` with no strip and none of the runtime rules
- backend/app/graph/runtime_policy.py:52-63 — build_policy_system_prompt composes `policy.persona_body` unstripped (dormant on prod today: installation_state is empty)

## Impact

Inconsistent candidate experience between lanes whenever a persona carries the legacy refusal lines the strip exists to remove, and any future correction to persona handling must be replicated per lane — the drift the single-assembly rule was meant to prevent.

## Suggested fix

Extract one `resolve_effective_persona(provider)` in context.py (fetch + strip, used by build_system_prompt) and call it from adapters.py:286; audit whether the manifest persona build should share it; drop the redundant second strip in build_system_prompt. This converges the assembly code path only — prompt content changes stay approval-gated.

## Notes

Carded as structure, not content: no persona text changes required.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
