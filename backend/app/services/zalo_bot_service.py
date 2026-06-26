"""Zalo Bot Platform client (bot-api.zaloplatforms.com) — the single Zalo
integration for inbound + outbound. Docs: https://bot.zaloplatforms.com/docs/apis/

Auth model: the bot token rides in the URL path (``/bot{TOKEN}/{method}``); there
is no Authorization header. Inbound webhook authenticity is verified via the
``X-Bot-Api-Secret-Token`` shared secret (see ``app.api.webhooks``) — NOT the
Zalo OA HMAC scheme.

``ZaloBotSender.send`` / ``.typing`` are OA-era compatibility shims used by the
graph runner + conversations router; the richer ``send_message`` / ``send_photo``
/ ``send_sticker`` / ``send_voice`` methods are available for future use.

Response envelope (per Zalo Bot Platform docs):

    { "ok": true,  "result": {...} }       — success
    { "ok": false, "error_code": int, "description": str }   — failure
    { "ok": true }                          — sendChatAction only (no result)

The auth model is: the bot token is embedded in the URL path
(``/bot{TOKEN}/{method}``); there is no Authorization header. All methods
are POST ``application/json``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result / response shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SendResult:
    """Uniform result returned by every sender method.

    ``ok``/``msg_id``/``error`` match the shape downstream persistence (and the
    OA-era call sites) expect; ``raw`` carries the full upstream envelope when
    the caller wants more than the parsed fields (e.g. for logging).
    """

    ok: bool
    msg_id: str | None = None
    error: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class BotInfo:
    """Result of ``getMe`` — basic bot identity."""

    id: str
    account_name: str
    account_type: str
    can_join_groups: bool
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookInfo:
    """Result of ``getWebhookInfo`` / ``setWebhook`` / ``deleteWebhook``.

    ``url`` is the empty string when no webhook is registered (i.e. after
    ``deleteWebhook``). ``updated_at`` is a millisecond Unix epoch.
    """

    url: str
    updated_at: int
    raw: dict[str, Any] = field(default_factory=dict)


# Chat action enum (documented values; ``upload_photo`` is "coming soon"
# per the docs and currently no-ops on the Zalo side).
ChatAction = Literal["typing", "upload_photo"]


# ---------------------------------------------------------------------------
# Shared low-level transport
# ---------------------------------------------------------------------------


class ZaloBotError(RuntimeError):
    """Raised when the upstream envelope is malformed (missing ``ok`` field).

    Distinct from a ``SendResult(ok=False)`` — a malformed envelope is a
    protocol bug, not a Zalo-reported failure.
    """


def _build_base_url(settings: Settings) -> str:
    """Compose the Bot Platform base URL; strips any trailing slash."""
    return settings.zalo_bot_api_base.rstrip("/")


def _method_url(settings: Settings, method: str) -> str:
    """Compose ``{base}/bot{TOKEN}/{method}`` per the Bot Platform contract.

    The token is a URL-path component; callers MUST treat it as a secret
    even though it never reaches a header (never log the full URL).
    """
    return f"{_build_base_url(settings)}/bot{settings.zalo_bot_token}/{method}"


async def _post(settings: Settings, method: str, body: dict[str, Any] | None) -> dict[str, Any]:
    """Single POST against the Bot Platform. Returns the parsed JSON envelope.

    Translates every failure mode into a dict so callers only need one
    ``if ``ok`` branch — never raises on HTTP / network errors. The token is
    injected via URL path, NOT an ``access_token`` header (different from
    the OA API).
    """
    if not settings.zalo_bot_token:
        return {"ok": False, "description": "zalo_bot_token not configured"}
    if not body:
        body = {}
    url = _method_url(settings, method)
    try:
        async with httpx.AsyncClient(timeout=settings.zalo_bot_request_timeout) as client:
            resp = await client.post(url, json=body)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "description": f"transport error: {exc}"}
    if not isinstance(data, dict):
        return {"ok": False, "description": f"non-JSON response: {data!r}"}
    if "ok" not in data:
        # Some endpoints (notably sendChatAction) omit ``result`` but still
        # return ``ok: true``; missing ``ok`` itself means the envelope is
        # genuinely malformed.
        return {"ok": False, "description": f"missing 'ok' in response: {data!r}"}
    return data


def _send_result(envelope: dict[str, Any]) -> SendResult:
    """Project a ``{ok, result/error_code/description}`` envelope into ``SendResult``.

    Sender methods all return ``{message_id, date}`` on success; we pluck
    ``message_id`` and surface the rest via ``raw``.
    """
    if envelope.get("ok"):
        result = envelope.get("result") or {}
        msg_id = result.get("message_id")
        return SendResult(ok=True, msg_id=str(msg_id) if msg_id is not None else None, raw=envelope)
    desc = envelope.get("description") or envelope.get("error_code") or "unknown error"
    return SendResult(ok=False, error=str(desc), raw=envelope)


# ---------------------------------------------------------------------------
# Outbound: sendMessage / sendPhoto / sendSticker / sendVoice / sendChatAction
# ---------------------------------------------------------------------------


class ZaloBotSender:
    """Outbound calls to the Zalo Bot Platform.

    Use one instance per process (stateless; safe to share). The constructor
    accepts settings explicitly so tests can inject a fixture; production
    callers can use ``ZaloBotSender()`` to read ``get_settings()`` lazily.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send(self, chat_id: str, text: str) -> SendResult:
        """OA-era compatibility shim: ``send(chat_id, text)`` -> sendMessage.
        Used by the graph runner + conversations router."""
        return await self.send_message(chat_id, text)

    async def typing(self, chat_id: str) -> SendResult:
        """Show a typing indicator. Best-effort; callers swallow errors."""
        return await self.send_chat_action(chat_id, "typing")

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: Literal["markdown", "html"] | None = None,
        text_styles: list[dict[str, Any]] | None = None,
    ) -> SendResult:
        """Send a 1-2000 char text message. See Zalo docs for ``text_styles`` shape."""
        if not 1 <= len(text) <= 2000:
            return SendResult(ok=False, error="text length must be 1..2000")
        body: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode is not None:
            body["parse_mode"] = parse_mode
        if text_styles is not None:
            body["text_styles"] = text_styles
        return _send_result(await _post(self._settings, "sendMessage", body))

    async def send_photo(self, chat_id: str, photo: str, caption: str | None = None) -> SendResult:
        """Send an image by URL/path. ``caption`` is 1-2000 chars if provided."""
        if caption is not None and not 1 <= len(caption) <= 2000:
            return SendResult(ok=False, error="caption length must be 1..2000 when provided")
        body: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption is not None:
            body["caption"] = caption
        return _send_result(await _post(self._settings, "sendPhoto", body))

    async def send_sticker(self, chat_id: str, sticker: str) -> SendResult:
        """Send a sticker by id from stickers.zaloapp.com."""
        return _send_result(
            await _post(self._settings, "sendSticker", {"chat_id": chat_id, "sticker": sticker})
        )

    async def send_voice(self, chat_id: str, voice_url: str) -> SendResult:
        """Send a ``.aac`` voice URL. 1-1 only — group chats are silently dropped upstream."""
        return _send_result(
            await _post(self._settings, "sendVoice", {"chat_id": chat_id, "voice_url": voice_url})
        )

    async def send_chat_action(self, chat_id: str, action: ChatAction) -> SendResult:
        """Show a transient status (``typing`` / ``upload_photo``) in the chat.

        Best-effort: callers should not fail the user-visible turn if this
        errors. Zalo's envelope for this method is ``{ok: true}`` only —
        ``message_id`` will always be ``None``.
        """
        envelope = await _post(self._settings, "sendChatAction", {"chat_id": chat_id, "action": action})
        # Custom projection: sendChatAction returns no ``result``, so the
        # generic ``_send_result`` (which looks for ``message_id``) would
        # always report ``msg_id=None``. That's fine — explicit for clarity.
        if envelope.get("ok"):
            return SendResult(ok=True, raw=envelope)
        desc = envelope.get("description") or envelope.get("error_code") or "unknown error"
        return SendResult(ok=False, error=str(desc), raw=envelope)


# ---------------------------------------------------------------------------
# Admin: getMe / getUpdates / setWebhook / deleteWebhook / getWebhookInfo
# ---------------------------------------------------------------------------


class ZaloBotAdminClient:
    """Bot Platform admin operations: identity, updates, webhook lifecycle.

    Webhook management belongs here, not on the sender, because it is
    configuration rather than per-turn traffic. ``getUpdates`` is also
    included: per the docs it is mutually exclusive with webhooks (Zalo
    disables long-polling once a webhook is registered), so callers should
    only invoke it on local/dev environments.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def get_me(self) -> SendResult:
        """Return a ``SendResult`` carrying ``BotInfo`` in ``raw`` on success.

        We deliberately reuse ``SendResult`` instead of raising because
        admin probes are typically best-effort (health checks, ops pages).
        Inspect ``raw`` to get the typed ``BotInfo`` fields.
        """
        envelope = await _post(self._settings, "getMe", None)
        if envelope.get("ok"):
            result = envelope.get("result") or {}
            # ``id`` is the only field callers actually need; the rest
            # default to empty strings / False if Zalo adds new fields.
            # If ``id`` is missing entirely, the envelope is malformed.
            if not isinstance(result, dict) or not result.get("id"):
                return SendResult(
                    ok=False, error="malformed getMe result: missing 'id'", raw=envelope
                )
            info = BotInfo(
                id=str(result.get("id", "")),
                account_name=str(result.get("account_name", "")),
                account_type=str(result.get("account_type", "")),
                can_join_groups=bool(result.get("can_join_groups", False)),
                raw=envelope,
            )
            return SendResult(ok=True, msg_id=info.id, raw={**envelope, "_parsed": info.__dict__})
        desc = envelope.get("description") or envelope.get("error_code") or "unknown error"
        return SendResult(ok=False, error=str(desc), raw=envelope)

    async def get_updates(self, timeout: int | None = None) -> SendResult:
        """Long-poll for new updates. Default timeout 30s per Zalo docs.

        Returns the raw list of events in ``raw["result"]`` so the caller can
        normalize them (the payload schema is shared with the webhook contract
        — see ``ZaloWebhookService.normalize``).
        """
        body: dict[str, Any] = {}
        if timeout is not None:
            body["timeout"] = str(timeout)
        envelope = await _post(self._settings, "getUpdates", body)
        if envelope.get("ok"):
            return SendResult(ok=True, raw=envelope)
        desc = envelope.get("description") or envelope.get("error_code") or "unknown error"
        return SendResult(ok=False, error=str(desc), raw=envelope)

    async def set_webhook(self, url: str, secret_token: str) -> SendResult:
        """Register a webhook URL + 8-256 char secret.

        Per the docs, Zalo will echo ``X-Bot-Api-Secret-Token: {secret_token}``
        on every inbound POST so the receiver can verify authenticity.
        Validation is enforced client-side too (the API will reject, but
        failing fast here surfaces a clearer error).
        """
        if not 8 <= len(secret_token) <= 256:
            return SendResult(ok=False, error="secret_token length must be 8..256")
        envelope = await _post(
            self._settings,
            "setWebhook",
            {"url": url, "secret_token": secret_token},
        )
        if envelope.get("ok"):
            return SendResult(ok=True, raw=envelope)
        desc = envelope.get("description") or envelope.get("error_code") or "unknown error"
        return SendResult(ok=False, error=str(desc), raw=envelope)

    async def delete_webhook(self) -> SendResult:
        """Unregister the webhook. After this, ``getUpdates`` becomes available."""
        envelope = await _post(self._settings, "deleteWebhook", None)
        if envelope.get("ok"):
            return SendResult(ok=True, raw=envelope)
        desc = envelope.get("description") or envelope.get("error_code") or "unknown error"
        return SendResult(ok=False, error=str(desc), raw=envelope)

    async def get_webhook_info(self) -> SendResult:
        """Return current webhook status. ``raw["result"]`` is the ``WebhookInfo`` payload."""
        envelope = await _post(self._settings, "getWebhookInfo", None)
        if envelope.get("ok"):
            return SendResult(ok=True, raw=envelope)
        desc = envelope.get("description") or envelope.get("error_code") or "unknown error"
        return SendResult(ok=False, error=str(desc), raw=envelope)
