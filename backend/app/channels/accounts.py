"""Neutral account-lifecycle status constants.

Phase 1 defined the *contract* for account authority; the real resolver is
backed by the ``ChannelAccount`` ORM model, with encrypted credentials
resolved provider-side (Phase 4 for Messenger). This module provides
:data:`ChannelAccountStatus` — lifecycle status constants.

Capability semantics (per the Phase 1 spec):

- ``ACTIVE``  — resolves send authority; full recruiter parity.
- ``INACTIVE`` — readable history scope; never resolves send authority. Send,
  retry, takeover/resume, and other send-capable mutations fail closed.

V1 enforces *at most one* active ``facebook_messenger`` account at the
registry/persistence layer (Phase 2 partial uniqueness).
"""

from __future__ import annotations


class ChannelAccountStatus:
    """Lifecycle status for a channel account.

    Plain string constants (not an enum) so they match the Alembic CHECK
    constraint verbatim and so future statuses can be added without a
    migration of this contract layer.
    """

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


__all__ = ["ChannelAccountStatus"]
