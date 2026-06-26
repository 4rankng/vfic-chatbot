"""Zalo OA messaging (server-side only — the OA token NEVER reaches the frontend)."""
import logging
import re
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()


@dataclass
class SendResult:
    ok: bool
    msg_id: str | None = None
    error: str | None = None


def strip_markdown(text: str) -> str:
    """Collapse common markdown to plain text for Zalo display (ported from n8n)."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    return text.strip()


class ZaloMessageService:
    async def send(self, zalo_chat_id: str, text: str) -> SendResult:
        body = strip_markdown(text)
        if not _settings.zalo_bot_token:
            logger.info("zalo send skipped (no OA token) chat=%s", zalo_chat_id)
            return SendResult(ok=False, error="zalo_bot_token not configured")

        try:
            async with httpx.AsyncClient(timeout=_settings.zalo_request_timeout) as client:
                resp = await client.post(
                    f"{_settings.zalo_api_base}/v3.0/oa/message",
                    headers={
                        "access_token": _settings.zalo_bot_token,
                        "Content-Type": "application/json",
                    },
                    json={
                        "recipient": {"conversation_id": zalo_chat_id},
                        "message": {"text": body},
                    },
                )
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return SendResult(ok=False, error=str(exc))

        if data.get("error") == 0:
            msg_id = (data.get("data") or {}).get("message_id")
            return SendResult(ok=True, msg_id=str(msg_id) if msg_id else None)
        return SendResult(ok=False, error=str(data.get("message") or data))

    async def typing(self, zalo_chat_id: str) -> None:
        if not _settings.zalo_bot_token:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{_settings.zalo_api_base}/v3.0/oa/typing",
                    headers={"access_token": _settings.zalo_bot_token},
                    json={"recipient": {"conversation_id": zalo_chat_id}},
                )
        except Exception:  # noqa: BLE001 — typing is best-effort
            pass
