"""Channel-neutral durable dispatch (Phase 3).

Wraps the provider send behind the registry so the graph, recruiter, proactive,
and outbox paths never branch on a provider id. The dispatch service resolves a
:class:`TextChannelAdapter` by provider from the :class:`ChannelAdapterRegistry`
and routes the :class:`OutboundTextCommand` to it.

Authority fence: the caller stamps ``channel_account_generation`` on the
command at creation time. The dispatch service compares it to the active
generation immediately before provider I/O and suppresses stale work across
disconnect/reconnect/replacement. (The runtime authority fence on the outbox
row remains separate; both must be current for a send to proceed.)

Phase 3 ships this as an additive layer. The existing
:func:`app.services.outbox_service.dispatch_outbox` path keeps working; callers
migrate to this service as they're rewired.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.channels import types as ct
from app.channels.registry import ChannelAdapterRegistry

if TYPE_CHECKING:
    from app.channels.ports import ChannelAccountResolver

logger = logging.getLogger(__name__)


class ChannelDispatchService:
    """Registry-driven provider-neutral send.

    The service is constructed per-request (or per-turn) with the registry and
    a channel-account resolver. It never reads secrets or config directly —
    adapters carry their own resolved credentials for their lifetime.
    """

    def __init__(
        self,
        registry: ChannelAdapterRegistry,
        *,
        account_resolver: "ChannelAccountResolver | None" = None,
    ) -> None:
        self._registry = registry
        self._resolver = account_resolver

    async def send(
        self,
        command: ct.OutboundTextCommand,
        *,
        before_provider_io: Callable[[], ct.ChannelSendResult | None] | None = None,
    ) -> ct.ChannelSendResult:
        """Route ``command`` to its provider adapter.

        Authority fence: if ``account_resolver`` is wired and the command's
        ``channel_account_generation`` is older than the active account's
        generation, the send is suppressed (the account was replaced/
        disconnected after the command was queued). Suppression is not a
        transport error and not retriable.
        """
        if self._resolver is not None:
            suppressed = await self._suppress_if_stale(command)
            if suppressed is not None:
                return suppressed

        adapter = self._registry.get(command.provider)
        if adapter is None:
            logger.warning(
                "channel dispatch: no adapter registered for provider=%s",
                command.provider,
            )
            return ct.ChannelSendResult(
                ok=False,
                error=f"no adapter registered for provider '{command.provider}'",
                error_class="provider_error",
                suppressed=True,
            )
        if before_provider_io is not None:
            blocked = before_provider_io()
            if blocked is not None:
                return blocked
        return await adapter.send_text(command)

    async def _suppress_if_stale(
        self, command: ct.OutboundTextCommand
    ) -> ct.ChannelSendResult | None:
        """Return a suppression result if the command's authority is stale.

        Returns ``None`` when the send should proceed (active account matches
        the command's generation, or no resolver is wired).
        """
        assert self._resolver is not None
        account = await self._resolver.resolve_active(
            provider=command.provider, account_key=command.account_key
        )
        if account is None:
            # No active account: suppress (e.g. disconnected Page, archived scope).
            return ct.ChannelSendResult(
                ok=False,
                error="channel account is not active",
                error_class="provider_error",
                suppressed=True,
            )
        if account.generation > command.channel_account_generation:
            # The account was reconnected/replaced after this command was
            # queued. Suppress rather than send under a superseded authority.
            return ct.ChannelSendResult(
                ok=False,
                error="channel account generation advanced before dispatch",
                error_class="provider_error",
                suppressed=True,
            )
        return None


def build_zalo_registry_from_config(
    cfg, *, oa_refresh=None, oa_account_key: str = ""
) -> ChannelAdapterRegistry:
    """Synchronously build a registry with Zalo adapters from a resolved config.

    The caller resolves :class:`ZaloRuntimeConfig` (Redis-cached, per-turn or
    per-request) and hands it here. This avoids any async bootstrap dance and
    keeps each adapter pinned to one config snapshot. ``oa_refresh`` is the
    zero-arg awaitable that refreshes the OA access token on demand; the caller
    is responsible for closing over the right settings-service instance.

    ``oa_account_key`` names the OA the config was resolved for, so the adapter
    scopes receipts to that account (multi-OA). The registry itself stays keyed
    by provider: one dispatch resolves one account's config and therefore needs
    exactly one OA adapter.
    """
    from app.channels.providers.zalo_bot import ZaloBotChannelAdapter
    from app.channels.providers.zalo_oa import ZaloOAChannelAdapter

    registry = ChannelAdapterRegistry()
    registry.register(ZaloBotChannelAdapter.from_config(cfg))
    registry.register(
        ZaloOAChannelAdapter.from_config(
            cfg, refresh=oa_refresh, account_key=oa_account_key
        )
    )
    return registry


def build_facebook_registry(fb_cfg) -> ChannelAdapterRegistry:
    """Build a registry with the Messenger adapter from a resolved Facebook config.

    The caller resolves :class:`FacebookRuntimeConfig` for the active Page
    (decrypting the Page token server-side via the account resolver). The
    registry contains only the Messenger adapter — Zalo dispatch goes through
    :func:`build_zalo_registry_from_config`.
    """
    from app.channels.providers.facebook_messenger import FacebookMessengerAdapter

    registry = ChannelAdapterRegistry()
    if fb_cfg is not None:
        registry.register(FacebookMessengerAdapter(fb_cfg))
    return registry


__all__ = [
    "ChannelDispatchService",
    "build_zalo_registry_from_config",
    "build_facebook_registry",
]
