"""Outbound transactional outbox internals.

Two responsibilities live here, split apart so a lifecycle change is not
reviewed against three provider branches:

- :mod:`app.services.outbox.repository` — the durable row: insert/upsert, the
  atomic PENDING claim, the sweep queries, and the status projections.
- :mod:`app.services.outbox.dispatcher` — the only part that talks to providers.

``app.services.outbox_service`` is the public facade and re-exports both;
import from there.
"""
