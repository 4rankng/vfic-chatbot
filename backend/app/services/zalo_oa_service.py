"""Zalo Official Account outbound client."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


from app.core.config import Settings, ZALO_OA_API_BASE, get_settings
from app.services.zalo_bot_service import (
    SendResult,
    _aggregate_chunked_send,
    _classify_transport_error,
    _split_long_plain_text,
)
from app.graph.outbound_telemetry import OutboundTelemetry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OAUserProfile:
    """Normalized subset of Zalo OA ``/v3.0/oa/user/detail`` we persist.

    ``avatar_url`` is chosen in priority order from the documented response:
    ``data.avatars.240`` > ``data.avatar`` > ``data.avatars.120``. Empty when
    Zalo returned no usable image so the caller keeps the initials fallback.
    """

    display_name: str = ""
    avatar_url: str = ""


@dataclass(frozen=True)
class _OaPostTiming:
    """Timing for one refresh-aware OA POST without retaining request data."""

    envelope: dict[str, Any]
    provider_request_ms: int
    provider_attempts: int
    retry_count: int
    retry_ms: int
    refresh_count: int
    refresh_ms: int


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
        refresh: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._access_token = access_token
        self._refresh = refresh

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
            # Reuse the process-scoped Zalo OA client (Tech-Lead Directive §4).
            # access_token is passed per-request (it rotates on refresh); the
            # client itself is auth-header-free so a refreshed token is always
            # picked up. The full URL is passed (no base_url) so the connection
            # pool is keyed on host while keeping the call shape unchanged.
            from app.core.http import get_http_client

            client = await get_http_client(
                "zalo_oa",
                timeout=self._settings.zalo_bot_request_timeout,
                settings=self._settings,
            )
            resp = await client.post(
                f"{ZALO_OA_API_BASE.rstrip('/')}{path}",
                json=body,
                headers={"access_token": token},
            )
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return {
                "error": -1,
                "message": f"transport error: {exc}",
                "error_class": _classify_transport_error(exc),
            }
        if isinstance(data, dict):
            return data
        return {"error": -1, "message": f"non-JSON response: {data!r}"}

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self._token
        if not token:
            return {"error": -1, "message": "zalo_oa_access_token not configured"}
        try:
            from app.core.http import get_http_client

            client = await get_http_client(
                "zalo_oa",
                timeout=self._settings.zalo_bot_request_timeout,
                settings=self._settings,
            )
            resp = await client.get(
                f"{ZALO_OA_API_BASE.rstrip('/')}{path}",
                params=params,
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
        return SendResult(
            ok=False,
            error=str(message),
            raw=envelope,
            error_class=envelope.get("error_class"),
        )

    @staticmethod
    def _is_token_invalid(envelope: dict[str, Any]) -> bool:
        """True when the OA envelope indicates the access_token is bad/expired."""
        error = envelope.get("error")
        if error in (0, "0", None):
            return False
        message = str(envelope.get("message") or envelope.get("error_message") or "").lower()
        if "access token" in message:
            return True
        if "token" in message and "invalid" in message:
            return True
        # Known Zalo OA token-related error codes.
        return str(error) in {"-216", "-213"}

    async def _post_with_refresh_timing(self, path: str, body: dict[str, Any]) -> _OaPostTiming:
        """POST, lazily refreshing the access_token once on a token-invalid reply.

        On a token-invalid envelope (and when a refresh callback is wired in) we
        refresh, swap the token, and retry exactly once. The new token sticks on
        ``self._access_token`` so a chunked send refreshes at most once per call.
        """
        request_t0 = time.monotonic()
        envelope = await self._post(path, body)
        provider_request_ms = int(round((time.monotonic() - request_t0) * 1000))
        provider_attempts = 1
        retry_count = 0
        retry_ms = 0
        refresh_count = 0
        refresh_ms = 0
        if self._is_token_invalid(envelope) and self._refresh is not None:
            refresh_count = 1
            refresh_t0 = time.monotonic()
            try:
                new_token = await self._refresh()
            except Exception:  # noqa: BLE001
                logger.warning("zalo OA access-token refresh failed", exc_info=True)
                refresh_ms = int(round((time.monotonic() - refresh_t0) * 1000))
                return _OaPostTiming(
                    envelope=envelope,
                    provider_request_ms=provider_request_ms,
                    provider_attempts=provider_attempts,
                    retry_count=retry_count,
                    retry_ms=retry_ms,
                    refresh_count=refresh_count,
                    refresh_ms=refresh_ms,
                )
            refresh_ms = int(round((time.monotonic() - refresh_t0) * 1000))
            if new_token:
                self._access_token = new_token
                retry_count = 1
                retry_t0 = time.monotonic()
                envelope = await self._post(path, body)
                retry_ms = int(round((time.monotonic() - retry_t0) * 1000))
                provider_request_ms += retry_ms
                provider_attempts += 1
        return _OaPostTiming(
            envelope=envelope,
            provider_request_ms=provider_request_ms,
            provider_attempts=provider_attempts,
            retry_count=retry_count,
            retry_ms=retry_ms,
            refresh_count=refresh_count,
            refresh_ms=refresh_ms,
        )

    async def _post_with_refresh(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Compatibility wrapper for non-chatbot OA callers."""
        return (await self._post_with_refresh_timing(path, body)).envelope

    async def _get_with_refresh(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """GET, refreshing and retrying once when Zalo rejects the access token."""
        envelope = await self._get(path, params=params)
        if self._is_token_invalid(envelope) and self._refresh is not None:
            try:
                new_token = await self._refresh()
            except Exception:  # noqa: BLE001
                logger.warning("zalo OA access-token refresh failed", exc_info=True)
                return envelope
            if new_token:
                self._access_token = new_token
                envelope = await self._get(path, params=params)
        return envelope

    async def send_message(
        self, chat_id: str, text: str, *, quote_message_id: str | None = None, **_: Any
    ) -> SendResult:
        prepare_t0 = time.monotonic()
        text = text.strip()
        if not text:
            return SendResult(
                ok=False,
                error="text length must be 1..2000",
                telemetry=OutboundTelemetry(adapter="zalo_oa", result="rejected"),
            )
        quote_message_id = (quote_message_id or "").strip()
        if not quote_message_id:
            return SendResult(
                ok=False,
                error="quote_message_id is required for OA CS replies",
                telemetry=OutboundTelemetry(adapter="zalo_oa", result="rejected"),
            )

        chunks = _split_long_plain_text(text)
        telemetry_base = OutboundTelemetry(
            adapter="zalo_oa",
            adapter_prepare_ms=int(round((time.monotonic() - prepare_t0) * 1000)),
        )
        if not self._token:
            return SendResult(
                ok=False,
                error="zalo_oa_access_token not configured",
                telemetry=telemetry_base.with_result("rejected"),
            )

        async def send_chunk(chunk: str) -> SendResult:
            body = {
                "recipient": {"user_id": chat_id},
                "message": {"text": chunk, "quote_message_id": quote_message_id},
            }
            timing = await self._post_with_refresh_timing("/v3.0/oa/message/cs", body)
            result = self._send_result(timing.envelope)
            return SendResult(
                ok=result.ok,
                msg_id=result.msg_id,
                error=result.error,
                raw=result.raw,
                error_class=result.error_class,
                telemetry=OutboundTelemetry(
                    adapter="zalo_oa",
                    provider_request_ms=timing.provider_request_ms,
                    provider_attempts=timing.provider_attempts,
                    retry_count=timing.retry_count,
                    retry_ms=timing.retry_ms,
                    refresh_count=timing.refresh_count,
                    refresh_ms=timing.refresh_ms,
                    chunk_count=1,
                    result="sent"
                    if result.ok
                    else ("transport_error" if result.error_class else "provider_error"),
                ),
            )

        return await _aggregate_chunked_send(
            chunks, send_chunk, telemetry_base=telemetry_base
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
        return self._send_result(await self._post_with_refresh("/v3.0/oa/message/cs", body))

    async def send_raw_message(self, chat_id: str, message: dict[str, Any]) -> SendResult:
        """Send a caller-built OA message payload through the CS endpoint."""
        if not message:
            return SendResult(ok=False, error="message body is required")
        body = {"recipient": {"user_id": chat_id}, "message": message}
        return self._send_result(await self._post_with_refresh("/v3.0/oa/message/cs", body))

    async def send_buttons(
        self,
        chat_id: str,
        *,
        text: str,
        buttons: list[dict[str, Any]],
    ) -> SendResult:
        """Send an OA button template (Quick Reply-style interactive message).

        Each button is ``{title, type, payload}`` with type one of
        ``oa.query.chat`` / ``oa.open.url`` / ``oa.query.show_product`` per the
        OA template docs. Routes through ``send_raw_message`` so it inherits the
        refresh-aware transport.
        """
        text = (text or "").strip()
        buttons = list(buttons or [])
        if not text:
            return SendResult(ok=False, error="text length must be 1..2000")
        if not buttons:
            return SendResult(ok=False, error="buttons list is required")
        message = {
            "text": text,
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": text,
                    "buttons": buttons,
                },
            },
        }
        return await self.send_raw_message(chat_id, message)

    async def send_anonymous_message(self, *, phone: str, text: str) -> SendResult:
        """Send a CS message addressed by phone number (no prior OA interaction).

        Recipient shape ``{"phone": phone}`` targets a user by phone instead of
        ``user_id``. Reuses the refresh-aware transport and standard result parsing.
        """
        text = (text or "").strip()
        phone = (phone or "").strip()
        if not text:
            return SendResult(ok=False, error="text length must be 1..2000")
        if not phone:
            return SendResult(ok=False, error="phone is required")
        body = {"recipient": {"phone": phone}, "message": {"text": text}}
        return self._send_result(await self._post_with_refresh("/v3.0/oa/message/cs", body))

    async def send_chat_action(self, chat_id: str, action: str) -> SendResult:
        # OA OpenAPI has no Bot-Platform-compatible typing endpoint in this app's
        # current contract. Log at debug so the no-op is observable in monitoring.
        # This adapter never sends an additional progress or acknowledgement
        # message; returns best-effort success so graph UX logic stays
        # channel-agnostic.
        logger.debug(
            "oa send_chat_action skipped (no OA typing endpoint): chat=%s action=%s",
            chat_id,
            action,
        )
        return SendResult(
            ok=True,
            raw={"skipped": True, "chat_id": chat_id, "action": action},
        )

    async def get_oa_info(self) -> SendResult:
        envelope = await self._get_with_refresh("/v2.0/oa/getoa")
        return self._send_result(envelope)

    async def get_user_detail(self, user_id: str) -> OAUserProfile | None:
        """Fetch a user's display name + avatar via ``GET /v3.0/oa/user/detail``.

        Zalo's v3 user-detail endpoint takes a compact JSON object
        ``{"user_id": "<oa-scoped id>"}`` URL-encoded into a ``data`` query param.
        Returns a normalized profile on success, or ``None`` for any transport
        error, malformed envelope, permission denial, or missing payload — the
        caller keeps the initials fallback in every case. Only structured,
        non-PII context is logged so Zalo responses never reach log streams.
        """
        user_id = (user_id or "").strip()
        if not user_id:
            return None
        # Pass raw JSON; httpx URL-encodes it once via params=. Previously we
        # pre-encoded with urllib.parse.quote, which httpx then encoded AGAIN
        # (turning %7B into %257B) — Zalo decoded once, saw still-encoded garbage,
        # and rejected every lookup with -201 "Data is not json format".
        data_param = json.dumps({"user_id": user_id}, separators=(",", ":"))
        envelope = await self._get_with_refresh("/v3.0/oa/user/detail", params={"data": data_param})
        if not isinstance(envelope, dict) or envelope.get("error") not in (0, "0", None):
            logger.info(
                "zalo OA user-detail lookup failed error=%s message=%s",
                envelope.get("error") if isinstance(envelope, dict) else "non-dict",
                envelope.get("message") if isinstance(envelope, dict) else None,
            )
            return None
        data = envelope.get("data")
        if not isinstance(data, dict):
            return None
        return _parse_oa_user_profile(data)


def _parse_oa_user_profile(data: dict[str, Any]) -> OAUserProfile:
    """Pick display_name + the best-documented avatar URL from a Zalo payload.

    Priority: ``avatars.240`` > ``avatar`` > ``avatars.120``. Returns empty
    strings when no usable image is present so callers fall back to initials.
    """
    display_name = str(data.get("display_name") or "").strip()

    avatars = data.get("avatars")
    avatar_240 = ""
    avatar_120 = ""
    if isinstance(avatars, dict):
        avatar_240 = str(avatars.get("240") or "").strip()
        avatar_120 = str(avatars.get("120") or "").strip()
    avatar = str(data.get("avatar") or "").strip()

    avatar_url = avatar_240 or avatar or avatar_120
    return OAUserProfile(display_name=display_name, avatar_url=avatar_url)
