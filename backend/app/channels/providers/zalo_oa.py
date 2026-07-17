"""Zalo Official Account adapter (Phase 3).

Wraps :class:`app.services.zalo_oa_service.ZaloOASender` behind the neutral
:class:`TextChannelAdapter` + :class:`ReceiptCapability` ports. The graph and
dispatch layers depend on the Protocol, never on this class.

Provider-owned responsibilities kept here: OA access-token custody (incl. lazy
refresh), the ``oa:`` storage-prefix convention, quote-message-id handling
(OA CS replies require quoting an inbound message), and the OA delivery/read
receipt event parser. The OA channel has no typing endpoint, so it does not
implement :class:`TypingCapability`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.channels import types as ct
from app.channels.ports import ReceiptCapability, TextChannelAdapter
from app.channels.providers.zalo_bot import _to_channel_result

if TYPE_CHECKING:
    from app.services.integration_settings import ZaloRuntimeConfig
    from app.services.zalo_oa_service import ZaloOASender


class ZaloOAChannelAdapter(TextChannelAdapter, ReceiptCapability):
    """Neutral port adapter for the Zalo Official Account."""

    provider = ct.PROVIDER_ZALO_OA

    def __init__(self, sender: "ZaloOASender") -> None:
        self._sender = sender

    @classmethod
    def from_config(
        cls, config: "ZaloRuntimeConfig", *, refresh
    ) -> "ZaloOAChannelAdapter":
        from app.services.zalo_oa_service import ZaloOASender

        return cls(ZaloOASender(access_token=config.oa_access_token, refresh=refresh))

    async def send_text(self, command: ct.OutboundTextCommand) -> ct.ChannelSendResult:
        # OA conversations store the scoped chat id as "oa:<user_id>"; the OA
        # Send API needs the raw user id. The legacy ZaloChannelSender stripped
        # this prefix; the adapter owns that storage convention now.
        recipient_id = command.recipient_id
        if recipient_id.startswith("oa:"):
            recipient_id = recipient_id.removeprefix("oa:")
        result = await self._sender.send_message(
            recipient_id,
            command.text,
            quote_message_id=command.reply_to_message_id or "",
        )
        return _to_channel_result(result, self.provider)

    def parse_receipt(self, payload: dict) -> ct.ChannelReceipt | None:
        """Project an already-authenticated OA webhook event into a neutral receipt.

        Returns ``None`` for non-receipt events. The caller (ingress service)
        is responsible for authenticity verification before calling this. The
        receipt is scoped to the OA account_key so cross-account message-id
        collisions are impossible.
        """
        kind_name = payload.get("event_name") or ""
        if kind_name == "user_seen_message":
            receipt_kind = "read"
        elif kind_name == "user_received_message":
            receipt_kind = "delivered"
        else:
            return None
        message = payload.get("message") or {}
        ids = []
        if isinstance(message, dict):
            raw_ids = message.get("msg_ids") or message.get("message_ids")
            if isinstance(raw_ids, str):
                ids = [raw_ids]
            elif isinstance(raw_ids, list):
                ids = [str(x) for x in raw_ids if x]
        mid = message.get("msg_id") if isinstance(message, dict) else None
        if mid and str(mid) not in ids:
            ids.append(str(mid))
        if not ids:
            return None
        return ct.ChannelReceipt(
            provider=self.provider,
            account_key="default:zalo_oa",
            provider_message_ids=tuple(ids),
            kind=receipt_kind,  # type: ignore[arg-type]
            occurred_at=datetime.now(timezone.utc),
        )


__all__ = ["ZaloOAChannelAdapter"]
