---
id: ARCH-14
title: "`app/capabilities/` is a live registry with a dormant, hash-verified extension API"
severity: medium
area: architecture
labels: [tech-debt]
effort: S
status: todo
found: 2026-09-24
---

# ARCH-14 — `app/capabilities/` is a live registry with a dormant, hash-verified extension API

**Severity:** medium · **Area:** architecture · **Effort:** S · **Labels:** tech-debt

## Problem

The registry's live half gates installation activation, but `resolve()`, `export_pack_contract()`, `ResolvedPack.adapter_descriptors` and `RecruitmentAdapterDescriptor` are reachable only from one test file, and several definition fields are hashed but never acted on.

## Evidence

- Live: `backend/app/api/installation_dependencies.py:19` and `backend/app/services/installation/service.py:89` call `get_capability_registry()`; `pack_contract_hash` at `service.py:222,321,542,828,864,958`; `IndustryPackDefinition.runtime_ready` at `service.py:961`.
- `backend/app/capabilities/registry.py:72` — `resolve()`, ~40 lines of kernel-ABI / schema-version / hash-verification logic; `:104` — `export_pack_contract()`; grep across `backend/` returns only `backend/tests/test_capability_registry.py:182,186-192,200,253,260`.
- `backend/app/capabilities/contracts.py:48` — `ResolvedPack.adapter_descriptors`, populated at `registry.py:97` and asserted only at `backend/tests/test_capability_registry.py:259`; `backend/app/capabilities/recruitment/adapter.py:6` — reachable only through it.
- `backend/app/capabilities/registry.py:126-145` — `workflow_ids`, `terminology_keys` and `compatible_operational_data` are hashed by `_pack_payload` but never read by production logic.

## Impact

The registry advertises a versioned, hash-verified extension point that no code path enters, so a reader must reason about ~40 lines of dormant verification logic to find out it is inert.

## Suggested fix

Keep `pack_contract_hash` and `validate_selection` — they gate installation activation and are load-bearing. Delete `resolve()`/`export_pack_contract()`/`ResolvedPack`/`adapter_descriptors`/`RecruitmentAdapterDescriptor`, or add the export endpoint that would use them.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
