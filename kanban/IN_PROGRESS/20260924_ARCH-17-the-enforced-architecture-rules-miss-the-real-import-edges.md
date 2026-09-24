---
id: ARCH-17
title: "The enforced architecture rules miss the real import edges"
severity: medium
area: architecture
labels: [tech-debt]
effort: S
status: in_progress
column: TODO
opened: 2026-09-24
---

# ARCH-17 — The enforced architecture rules miss the real import edges

**Severity:** medium · **Area:** architecture · **Effort:** S · **Labels:** tech-debt

**Trạng thái:** TODO

## Problem

The layering rules the two architecture tests encode cover only part of the app, so the edges that actually violate the ports-first intent sit outside the guard and the guard gives false confidence.

## Evidence

- `backend/app/realtime/socketio.py:25` — `from app.api.auth_dependencies import get_user_from_token`, transport importing the HTTP auth layer; `realtime/` is not a covered source in `_backend_rule`. `backend/app/services/presence.py:22` — `from app.realtime.emitter import emit_event`, which `service_outward` does not forbid (it lists only `app.{graph,workers,api}`).
- `backend/app/reporting/infrastructure/conversation_attention.py:32` — imports `app.services.conversation.repository` although only `reporting/application` is a pure prefix; `backend/app/channels/providers/facebook_account.py:27-28` — imports `app.models.channel_account` and `app.services.audit_service`, and `channels/` is entirely uncovered by the rules.
- `backend/app/models/conversation.py:26`, `backend/app/models/job.py:13`, `backend/app/models/lead.py:26` and `backend/app/models/knowledge.py:20` — models import enums from contexts above them, inverting the documented `API → Services → Models/Core` direction.
- `backend/app/api/integrations.py:792,830,892,922,1025,1050,1173,1261,1284,1310,1339` and `backend/app/api/webhooks.py:160,183,213,265` — the API layer imports channel providers, which `api_outward` does not list.
- The three edges the brief expected to find — `services → api`, `models → services`, `graph → concrete services` — are all absent and machine-enforced with a zero-entry allowlist (`backend/tests/test_architecture_boundaries.py:19`, `backend/tests/test_graph_import_guard.py:35`). Verified, not a defect.

## Impact

The next boundary violation lands outside the rule set, exactly as these did. The model inversions are enum-only so the runtime impact is low, but they invert the documented direction and make the rule set's coverage claim misleading.

## Suggested fix

Add `app.realtime`, `app.channels` and `app.reporting` to the covered source list in `_backend_rule` and add `app.channels` to the `api_outward` target list; each new rule surfaces a small, fixed set of edges, and the first three rows are a one-line import inversion each — e.g. `presence.py` should publish through `conversation_messaging.application.ports.ConversationEventsPort`, which already exists at `conversation_messaging/application/ports.py:39`. Narrow the `factories.py` exemption in `test_graph_import_guard.py:35` at the same time (see ARCH-09).

## Notes

Split from a merged ticket. The named duplication pairs from audit finding F18 are now ARCH-19; F18's FAQ and grounding items are ARCH-02 and ARCH-05.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
