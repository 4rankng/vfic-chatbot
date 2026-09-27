"""Channel-aware Zalo sender facade."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.channels.types import oa_user_id
from app.models.conversation import Conversation
from app.services.integration_settings import ZaloRuntimeConfig
from app.services.zalo_bot_service import SendResult, ZaloBotSender
from app.services.zalo_oa_service import ZaloOASender


def external_chat_id(conv: Conversation) -> str:
    """The provider-side recipient for one conversation.

    OA conversations store an alias (``oa:<user_id>`` on the original OA,
    ``oa:<account_key>:<user_id>`` on any other), while the OA Send API takes
    the bare user id; Bot/Messenger aliases are already the recipient.
    """
    channel = getattr(conv, "zalo_channel", None) or "bot"
    chat_id = conv.zalo_chat_id
    if channel == "oa":
        return oa_user_id(chat_id)
    return chat_id


class ZaloChannelSender:
    """Dispatches outbound messages to Bot Platform or OA by conversation channel."""

    def __init__(
        self,
        config: ZaloRuntimeConfig,
        *,
        refresh: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        self._bot = ZaloBotSender(bot_token=config.bot_token)
        self._oa = ZaloOASender(access_token=config.oa_access_token, refresh=refresh)

    def for_conversation(self, conv: Conversation):
        if (getattr(conv, "zalo_channel", None) or "bot") == "oa":
            return _BoundSender(self._oa, external_chat_id(conv))
        return _BoundSender(self._bot, external_chat_id(conv))

    async def send_payload(self, channel: str, payload: dict[str, Any]) -> SendResult:
        """Dispatch one immutable outbox payload without consulting live state."""
        chat_id = str(payload.get("chat_id") or "")
        text = str(payload.get("text") or "")
        if not chat_id or not text:
            return SendResult(ok=False, error="outbound payload is missing chat_id or text")
        if channel == "zalo_oa":
            return await self._oa.send_message(
                oa_user_id(chat_id),
                text,
                quote_message_id=str(payload.get("quote_message_id") or ""),
            )
        if channel == "zalo_bot":
            return await self._bot.send_message(chat_id, text)
        return SendResult(ok=False, error=f"unsupported outbound channel: {channel}")


class _BoundSender:
    def __init__(self, sender, chat_id: str) -> None:
        self._sender = sender
        self._chat_id = chat_id

    async def send_message(self, _chat_id: str, text: str, **kwargs) -> SendResult:
        return await self._sender.send_message(self._chat_id, text, **kwargs)

    async def send_chat_action(self, _chat_id: str, action: str) -> SendResult:
        return await self._sender.send_chat_action(self._chat_id, action)

    async def send_buttons(
        self, _chat_id: str, *, text: str, buttons: list[dict[str, Any]]
    ) -> SendResult:
        return await self._sender.send_buttons(self._chat_id, text=text, buttons=buttons)

    async def send_media(
        self,
        _chat_id: str,
        *,
        text: str,
        media_url: str,
        media_type: str = "image",
    ) -> SendResult:
        return await self._sender.send_media(
            self._chat_id,
            text=text,
            media_url=media_url,
            media_type=media_type,
        )
