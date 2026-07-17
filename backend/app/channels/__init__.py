"""Channel-neutral messaging boundary.

This package owns the *provider-neutral* contracts shared by API ingress,
graph dispatch, recruiter delivery, workers, and provider adapters. It is an
application boundary, not a graph-owned surface: ingress and recruiter
delivery consume these ports too, so they must not live under ``app/graph/``.

Boundaries (see ``AGENTS.md``):

- ``app.api/``          — HTTP transport only.
- ``app.services/``     — business logic; depends on these Protocols, not on
                          concrete provider modules.
- ``app.graph/``        — bot-turn behavior; depends on ``graph/ports.py``
                          Protocols, which may compose these contracts.
- ``app.channels/``     — neutral value objects, ports, registry, and account
                          authority. Concrete provider adapters live under
                          ``app/channels/providers/``.

Responsibility split:

- **Shared here:** identity refs, inbound text, outbound text command, send
  result, receipt, optional capability protocols, account status, registry.
- **Provider-owned (inside ``providers/``):** OAuth, tokens, raw webhook
  payloads, receipts, retry classification, messaging-window policy.

Phase 1 is purely additive: no runtime path is changed. Runtime wiring starts
in Phase 3 once the Phase 2 identity migration is approved.
"""

from __future__ import annotations

__all__: list[str] = []
