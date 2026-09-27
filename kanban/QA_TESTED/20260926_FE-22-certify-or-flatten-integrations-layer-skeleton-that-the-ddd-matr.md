---
id: FE-22
title: "Certify or flatten integrations/ layer skeleton that the DDD matrix leaves unenforced"
severity: medium
area: frontend
labels: [architecture, frontend, enforcement-gap]
effort: M
status: done
column: QA_TESTED

opened: 2026-09-26
---

# FE-22 — Certify or flatten integrations/ layer skeleton that the DDD matrix leaves unenforced

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** architecture, frontend, enforcement-gap

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

The sweep rebuilt integrations/ with the DDD directory skeleton (domain/, application/, presentation/ plus a root api.ts gateway), but the certified dependency matrix in backend/tests/test_architecture_boundaries.py only enforces knowledge, leads, personas, projects, and reporting. The layer rules never fire for integrations, and its layers already sit in directions the certified rules forbid elsewhere: the application layer imports the api.ts gateway (which imports @/lib/apiClient), domain imports types from that transport module, and presentation reaches past application into ../api and the root-level SettingsFieldStatus.

## Evidence

- backend/tests/test_architecture_boundaries.py:243-246 — _FRONTEND_LAYERED_FEATURE_ROOTS covers only knowledge, leads, personas, projects, reporting; 'integrations' is absent
- frontend/src/components/atomic-crm/integrations/application/useSettingsBundle.ts:9-14 — the application layer imports zaloIntegrationGateway from ../api, whose first import is apiJson from @/lib/apiClient (integrations/api.ts:1-2) — the exact application→lib edge certified features forbid
- frontend/src/components/atomic-crm/integrations/application/useZaloForm.ts:5 — same edge: application hook imports the gateway from ../api
- frontend/src/components/atomic-crm/integrations/domain/providerDescriptors.ts:12-13 — domain imports type SecretStatus from ../api, tying domain to the transport module
- frontend/src/components/atomic-crm/integrations/presentation/ZaloChannelSection.tsx:6-8 — presentation imports ../api types and the root-level ../SettingsFieldStatus, bypassing the application layer

## Impact

Nothing stops integrations/ from drifting further, and the file layout misleads contributors into thinking the layers are enforced like projects/ or leads/. The next person adding the feature to the matrix inherits 4+ pre-existing violations to untangle.

## Suggested fix

Either (a) finish the migration: define an integrations/application port (like project-knowledge-port.ts), move the gateway behind integrations/infrastructure/, point application hooks at the port, and add 'integrations' to _FRONTEND_LAYERED_FEATURE_ROOTS with composition-module entries; or (b) explicitly flatten the domain/application/presentation dirs with a comment that the feature is uncertified, so nobody mistakes them for enforced layers.

## Notes

Distinct from the two known QA-blocked edges (FE-02/FE-08 application-layer edges, ChatThread/use-conversation-actions provider seam) — this is a whole unenforced feature tree.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
