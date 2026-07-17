"""Concrete provider adapters.

Provider-owned responsibilities live here: OAuth, token custody, raw webhook
payload parsing, signature verification, receipt normalization, retry
classification, and messaging-window policy. Shared services must not import
any module from this package directly — they resolve through
:class:`app.channels.registry.ChannelAdapterRegistry`.

Phase 1: empty boundary. Zalo Bot/OA wrappers land in Phase 3; the Facebook
OAuth client, account resolver, signature verifier, policy, and Messenger
adapter land in Phases 4–5.
"""

from __future__ import annotations

__all__: list[str] = []
