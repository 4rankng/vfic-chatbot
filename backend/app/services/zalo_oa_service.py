"""Zalo Official Account outbound client."""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, ZALO_OA_API_BASE, get_settings
from app.services.zalo_bot_service import SendResult, _split_long_plain_text


class ZaloOASender:
    """Outbound calls to Zalo Official Account OpenAPI.

    It intentionally mirrors the small subset of ``ZaloBotSender`` used by the
    graph: ``send_message`` and best-effort ``send_chat_action``.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        access_token: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._access_token = access_token

    @property
    def _token(self) -> str:
        if self._access_token is not None:
            return self._access_token
        return self._settings.zalo_oa_access_token

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = self._token
        if not token:
            return {"error": -1, "message": "zalo_oa_access_token not configured"}
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.zalo_bot_request_timeout
            ) as client:
                resp = await client.post(
                    f"{ZALO_OA_API_BASE.rstrip('/')}{path}",
                    json=body,
                    headers={"access_token": token},
                )
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return {"error": -1, "message": f"transport error: {exc}"}
        if isinstance(data, dict):
            return data
        return {"error": -1, "message": f"non-JSON response: {data!r}"}

    async def _get(self, path: str) -> dict[str, Any]:
        token = self._token
        if not token:
            return {"error": -1, "message": "zalo_oa_access_token not configured"}
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.zalo_bot_request_timeout
            ) as client:
                resp = await client.get(
                    f"{ZALO_OA_API_BASE.rstrip('/')}{path}",
                    headers={"access_token": token},
                )
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return {"error": -1, "message": f"transport error: {exc}"}
        if isinstance(data, dict):
            return data
        return {"error": -1, "message": f"non-JSON response: {data!r}"}

    @staticmethod
    def _send_result(envelope: dict[str, Any]) -> SendResult:
        error = envelope.get("error", 0)
        if error in (0, "0", None):
            data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
            msg_id = data.get("message_id") or data.get("msg_id")
            return SendResult(
                ok=True,
                msg_id=str(msg_id) if msg_id is not None else None,
                raw=envelope,
            )
        message = envelope.get("message") or envelope.get("error_message") or error
        return SendResult(ok=False, error=str(message), raw=envelope)

    async def send_message(self, chat_id: str, text: str, **_: Any) -> SendResult:
        text = text.strip()
        if not text:
            return SendResult(ok=False, error="text length must be 1..2000")

        chunks = _split_long_plain_text(text)
        envelopes: list[dict[str, Any]] = []
        message_ids: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            body = {
                "recipient": {"user_id": chat_id},
                "message": {"text": chunk},
            }
            result = self._send_result(await self._post("/v3.0/oa/message/cs", body))
            envelopes.append(result.raw or {})
            if result.msg_id:
                message_ids.append(result.msg_id)
            if not result.ok:
                return SendResult(
                    ok=False,
                    msg_id=message_ids[0] if message_ids else None,
                    error=f"chunk {index}/{len(chunks)} failed: {result.error}",
                    raw={"chunks": envelopes, "message_ids": message_ids},
                )
        return SendResult(
            ok=True,
            msg_id=message_ids[0] if message_ids else None,
            raw={"chunks": envelopes, "message_ids": message_ids},
        )

    async def send_media(
        self,
        chat_id: str,
        *,
        text: str,
        media_url: str,
        media_type: str = "image",
    ) -> SendResult:
        """Send an OA consultation message with one media attachment.

        Zalo's CS media template supports a single media element. The current
        chatbot primarily sends text, but this helper gives recruiter/admin
        workflows a documented OA-native shape for image/GIF responses.
        """
        text = text.strip()
        media_url = media_url.strip()
        media_type = media_type.strip()
        if not text:
            return SendResult(ok=False, error="text length must be 1..2000")
        if len(text) > 2000:
            return SendResult(ok=False, error="text length must be 1..2000")
        if not media_url:
            return SendResult(ok=False, error="media_url is required")
        if media_type not in {"image", "gif"}:
            return SendResult(ok=False, error="media_type must be image or gif")

        body = {
            "recipient": {"user_id": chat_id},
            "message": {
                "text": text,
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "media",
                        "elements": [
                            {
                                "media_type": media_type,
                                "url": media_url,
                            }
                        ],
                    },
                },
            },
        }
        return self._send_result(await self._post("/v3.0/oa/message/cs", body))

    async def send_raw_message(self, chat_id: str, message: dict[str, Any]) -> SendResult:
        """Send a caller-built OA message payload through the CS endpoint."""
        if not message:
            return SendResult(ok=False, error="message body is required")
        body = {"recipient": {"user_id": chat_id}, "message": message}
        return self._send_result(await self._post("/v3.0/oa/message/cs", body))

    async def send_chat_action(self, chat_id: str, action: str) -> SendResult:
        # OA OpenAPI has no Bot-Platform-compatible typing endpoint in this app's
        # current contract. Treat it as best-effort success so graph UX logic can
        # stay channel-agnostic.
        return SendResult(
            ok=True,
            raw={"skipped": True, "chat_id": chat_id, "action": action},
        )

    async def get_oa_info(self) -> SendResult:
        envelope = await self._get("/v2.0/oa/getoa")
        return self._send_result(envelope)
