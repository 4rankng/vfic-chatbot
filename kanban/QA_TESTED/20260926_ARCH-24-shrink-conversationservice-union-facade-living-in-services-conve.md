---
id: ARCH-24
title: "Shrink ConversationService union facade living in services/conversation/__init__.py"
severity: medium
area: architecture
labels: [leaky-abstraction, facade]
effort: M
status: done
column: QA_TESTED
opened: 2026-09-26
---

# ARCH-24 — Shrink ConversationService union facade living in services/conversation/__init__.py

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** leaky-abstraction, facade

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

The ConversationService facade is defined inside the package __init__.py and re-exposes the union of ConversationRepository, ConversationState and the event bus with hand-copied full signatures — 527 lines of mostly one-line delegations. Every new state/repo method must be manually mirrored here or consumers silently miss it, and every signature change is edited twice. Importing app.services.conversation also pulls the entire state machine, which forced the TYPE_CHECKING dance at the top of the file.

## Evidence

- backend/app/services/conversation/__init__.py:17 — module docstring: facade composing repository/event bus/state, re-exposing the union of public methods; 527 lines
- backend/app/services/conversation/__init__.py:150-283 — verified stretch of pure forwarders (ensure_by_identity, record_inbound, acquire_lock, release_lock, renew_lock, recheck_ownership, claim_send, finalize_outbound_dispatch) each duplicating the full parameter list of self.state.*
- backend/app/services/conversation/__init__.py:20-24 — runtime imports of the three submodules plus TYPE_CHECKING-only model imports to dodge circulars
- backend/app/graph/ports.py:140 — ConversationPort already declares the narrowed surface the graph brain needs, so the wide union serves only api/services callers

## Impact

Signature drift between state/repo and the facade is caught only at call time; contributors adding a ConversationState method must know to touch __init__.py, and the package's import side effects grow with every facade line.

## Suggested fix

Move the ConversationService class verbatim to services/conversation/service.py, leaving __init__.py re-exporting ConversationService/ConversationConflict (one line each, zero import-behavior change). Then expose the composed parts directly (service.state / service.repo are public today) and migrate api/conversations.py + services/webhook.py call sites to the named part they mean, keeping graph consumers on ConversationPort. Delete forwarders once no caller remains.

## Notes

claim_send is one of the forwarders — it is a verified-atomic seam (README not-tickets); preserve the delegation target exactly.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
