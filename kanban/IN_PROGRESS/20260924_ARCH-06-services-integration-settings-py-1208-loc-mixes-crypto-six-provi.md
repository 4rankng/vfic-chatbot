---
id: ARCH-06
title: "`services/integration_settings.py` (1208 LOC) mixes crypto, six provider groups and cache invalidation"
severity: medium
area: architecture
labels: [tech-debt]
effort: M
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# ARCH-06 — `services/integration_settings.py` (1208 LOC) mixes crypto, six provider groups and cache invalidation

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** IN_PROGRESS

## Problem

One module holds the AES-GCM credential cipher, six provider resolve/admin-view pairs each with its own key set, and the cache-namespace invalidation mechanics. The cipher has no dependency on any provider, and the provider groups share only the storage primitives.

## Evidence

- `backend/app/services/integration_settings.py:264-323` — `IntegrationSettingsCipher` (AES-GCM, `v1:`/`v2:` versioning, AEAD context binding), independent of every provider.
- `backend/app/services/integration_settings.py:406,427,759,781` — Zalo; `:460,478,876` — MiniMax; `:494,520,911` — OpenRouter; `:539,574,674` — custom LLM; `:593,615,627` — Jev; `:1012,1036,1059,1086,1150,1188,1194,1204` — Facebook app and per-Page.
- `backend/app/services/integration_settings.py:942,705,732,964,996,352` — `_bump_provider_namespaces`, `_write_setting`, `_write_secret`, `record_provider_test_result`, `invalidate_facebook_cache`, `normalize_llm_failover_order`.

## Impact

Every provider credential path runs through one 1208-line module, so a change to any provider's key set is reviewed against the other five and the cipher is reachable from code that has nothing to do with encryption.

## Suggested fix

Natural seam: `services/integration_settings/{cipher,providers/{zalo,llm,facebook},storage}.py`. `IntegrationSettingsService` keeps its public method names (called from `api/integrations.py`, `graph/factories.py:637`, `workers/persistence_worker.py:74` and `services/installation/service.py`) and becomes a facade composing the three provider groups — the same facade pattern already used by `ConversationService` (`services/conversation/__init__.py:36`).

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
