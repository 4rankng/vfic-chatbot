"""Zalo Bot Platform adapter (Phase 3).

Wraps the existing :class:`app.services.zalo_bot_service.ZaloBotSender` behind
the neutral :class:`TextChannelAdapter` + :class:`TypingCapability` ports. The
graph/dispatch/ingress layers depend on the Protocol, never on this class.

Provider-owned responsibilities kept here: token resolution (the Bot token
rides in the URL path), raw payload construction, transport-error
classification via the shared taxonomy, and the typing chat action. The
Bot Platform has no delivery/read receipts, so no :class:`ReceiptCapability`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.channels import types as ct
from app.channels.ports import TextChannelAdapter, TypingCapability

if TYPE_CHECKING:
    from app.services.integration_settings import ZaloRuntimeConfig
    from app.services.zalo_bot_service import ZaloBotSender


class ZaloBotChannelAdapter(TextChannelAdapter, TypingCapability):
    """Neutral port adapter for the Zalo Bot Platform.

    The adapter is constructed per-dispatch (or per-turn) with a resolved
    :class:`ZaloRuntimeConfig`; it never reads config itself. The token never
    enters a queue payload — the caller (dispatch service) resolves authority
    server-side and the adapter uses it only for the lifetime of one send.
    """

    provider = ct.PROVIDER_ZALO_BOT

    def __init__(self, sender: "ZaloBotSender") -> None:
        self._sender = sender

    @classmethod
    def from_config(cls, config: "ZaloRuntimeConfig") -> "ZaloBotChannelAdapter":
        from app.services.zalo_bot_service import ZaloBotSender

        return cls(ZaloBotSender(bot_token=config.bot_token))

    async def send_text(self, command: ct.OutboundTextCommand) -> ct.ChannelSendResult:
        result = await self._sender.send_message(command.recipient_id, command.text)
        return _to_channel_result(result, self.provider)

    async def send_typing(self, *, account_key: str, recipient_id: str) -> ct.ChannelSendResult:
        result = await self._sender.send_chat_action(recipient_id, "typing")
        return _to_channel_result(result, self.provider)


def _to_channel_result(result, provider: str) -> ct.ChannelSendResult:
    """Map a Zalo :class:`SendResult` to the neutral :class:`ChannelSendResult`.

    ``error_class`` is required on failure (Phase 1 contract) and is preserved
    from the sender's classification; when the sender did not classify (e.g. a
    provider envelope rejection) it falls back to ``provider_error``.
    """
    if result.ok:
        return ct.ChannelSendResult(
            ok=True,
            provider_message_id=result.msg_id,
            telemetry=result.telemetry,
        )
    error_class = result.error_class or "provider_error"
    return ct.ChannelSendResult(
        ok=False,
        provider_message_id=result.msg_id,
        error=result.error,
        error_class=error_class,  # type: ignore[arg-type]
        telemetry=result.telemetry,
    )


__all__ = ["ZaloBotChannelAdapter"]
