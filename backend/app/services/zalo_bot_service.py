"""Zalo Bot Platform client (bot-api.zaloplatforms.com) — the single Zalo
integration for inbound + outbound. Docs: https://bot.zaloplatforms.com/docs/apis/

Auth model: the bot token rides in the URL path (``/bot{TOKEN}/{method}``); there
is no Authorization header. Inbound webhook authenticity is verified via the
``X-Bot-Api-Secret-Token`` shared secret (see ``app.api.webhooks``) — NOT the
Zalo OA HMAC scheme.

Text, media, sticker, voice, and chat-action sends map directly to Bot Platform
methods.

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
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal


from app.core.config import Settings, ZALO_BOT_API_BASE, get_settings
from app.graph.outbound_telemetry import (
    OutboundTelemetry,
    combine_outbound_telemetry,
)

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

    ``error_class`` disambiguates transport failures so the runner can classify
    ambiguous sends (timeout / reset AFTER the request may have reached the
    provider) as ``SEND_UNKNOWN`` rather than retryable ``FAILED``. ``None`` on
    success and on definite upstream-rejected envelopes. Set by the sender's
    ``_post`` transport-error branch; see ``_TRANSPORT_ERROR_CLASS``.
    """

    ok: bool
    msg_id: str | None = None
    error: str | None = None
    raw: dict[str, Any] | None = None
    error_class: str | None = None
    telemetry: OutboundTelemetry | None = None


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
ZALO_MAX_TEXT_CHARS = 2000
ZALO_VISIBLE_BUBBLE_CHARS = 420


# ---------------------------------------------------------------------------
# Transport-error classification (re-exported from the graph layer)
# ---------------------------------------------------------------------------
#
# The classifier + AMBIGUOUS_SEND_CLASSES live in app.graph.send_classification
# (a leaf utility with no service deps) so the graph runner can import the
# constant without re-introducing the graph<->services cycle. The services
# layer imports it here (services → graph is the allowed direction) and the
# senders' ``_post`` swallows stamp the error_class onto the returned envelope.

from app.graph.send_classification import (  # noqa: E402 — after constants for grouping
    classify_transport_error as _classify_transport_error,
)


# ---------------------------------------------------------------------------
# Shared low-level transport
# ---------------------------------------------------------------------------


class ZaloBotError(RuntimeError):
    """Raised when the upstream envelope is malformed (missing ``ok`` field).

    Distinct from a ``SendResult(ok=False)`` — a malformed envelope is a
    protocol bug, not a Zalo-reported failure.
    """


def _build_base_url(_settings: Settings) -> str:
    """Compose the Bot Platform base URL; strips any trailing slash."""
    return ZALO_BOT_API_BASE.rstrip("/")


def _method_url(settings: Settings, method: str, token: str | None = None) -> str:
    """Compose ``{base}/bot{TOKEN}/{method}`` per the Bot Platform contract.

    The token is a URL-path component; callers MUST treat it as a secret
    even though it never reaches a header (never log the full URL).
    """
    return f"{_build_base_url(settings)}/bot{token or settings.zalo_bot_token}/{method}"


async def _post(
    settings: Settings,
    method: str,
    body: dict[str, Any] | None,
    *,
    token: str | None = None,
) -> dict[str, Any]:
    """Single POST against the Bot Platform. Returns the parsed JSON envelope.

    Translates every failure mode into a dict so callers only need one
    ``if ``ok`` branch — never raises on HTTP / network errors. The token is
    injected via URL path, NOT an ``access_token`` header (different from
    the OA API).
    """
    resolved_token = token if token is not None else settings.zalo_bot_token
    if not resolved_token:
        return {"ok": False, "description": "zalo_bot_token not configured"}
    if not body:
        body = {}
    url = _method_url(settings, method, resolved_token)
    try:
        # Reuse the process-scoped Zalo Bot Platform client (Tech-Lead
        # Directive §4) — fresh TLS handshakes per send were ~100-300 ms of
        # pure overhead on every candidate reply. The full URL (with token in
        # path) is passed here because the client is constructed without a
        # base_url; auth rides the path, never a header.
        from app.core.http import get_http_client

        client = await get_http_client(
            "zalo_bot",
            timeout=settings.zalo_bot_request_timeout,
            settings=settings,
        )
        resp = await client.post(url, json=body)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "description": f"transport error: {exc}",
            "error_class": _classify_transport_error(exc),
        }
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

    Message-bearing methods return ``{message_id, date}`` inside ``result``; we
    pluck ``message_id`` and surface the rest via ``raw``. Methods whose
    ``result`` is missing or not a dict (admin list payloads, ``{ok: true}``
    chat-action acks) yield ``msg_id=None`` — the same projection every per-method
    tail used before they delegated here.
    """
    if envelope.get("ok"):
        result = envelope.get("result")
        result_dict = result if isinstance(result, dict) else {}
        msg_id = result_dict.get("message_id")
        return SendResult(ok=True, msg_id=str(msg_id) if msg_id is not None else None, raw=envelope)
    desc = envelope.get("description") or envelope.get("error_code") or "unknown error"
    return SendResult(
        ok=False,
        error=str(desc),
        raw=envelope,
        error_class=envelope.get("error_class"),
    )


async def _aggregate_chunked_send(
    chunks: list[str],
    send_chunk: Callable[[str], Awaitable[SendResult]],
    *,
    telemetry_base: OutboundTelemetry | None = None,
) -> SendResult:
    """Send each chunk via ``send_chunk`` and fold the per-chunk results.

    Aggregation is channel-agnostic: every raw envelope is preserved, the first
    ``msg_id`` wins, the first failed chunk short-circuits with a
    ``chunk N/M failed`` error, and a clean run returns the first ``msg_id``
    with the full envelope trail in ``raw``. Channel differences — body shape,
    transport, token refresh, per-chunk validation — live in the ``send_chunk``
    callback, so the Bot and OA senders share this fold verbatim.
    """
    envelopes: list[dict[str, Any]] = []
    message_ids: list[str] = []
    chunk_telemetry: list[OutboundTelemetry] = []
    for index, chunk in enumerate(chunks, start=1):
        result = await send_chunk(chunk)
        envelopes.append(result.raw or {})
        if result.telemetry is not None:
            chunk_telemetry.append(result.telemetry)
        if result.msg_id:
            message_ids.append(result.msg_id)
        if not result.ok:
            telemetry = (
                combine_outbound_telemetry(
                    telemetry_base,
                    chunk_telemetry,
                    result="transport_error" if result.error_class else "provider_error",
                )
                if telemetry_base is not None
                else None
            )
            return SendResult(
                ok=False,
                msg_id=message_ids[0] if message_ids else None,
                error=f"chunk {index}/{len(chunks)} failed: {result.error}",
                raw={"chunks": envelopes, "message_ids": message_ids},
                error_class=result.error_class,
                telemetry=telemetry,
            )
    telemetry = (
        combine_outbound_telemetry(telemetry_base, chunk_telemetry, result="sent")
        if telemetry_base is not None
        else None
    )
    return SendResult(
        ok=True,
        msg_id=message_ids[0] if message_ids else None,
        raw={"chunks": envelopes, "message_ids": message_ids},
        telemetry=telemetry,
    )


def _split_long_plain_text(
    text: str,
    max_chars: int = ZALO_VISIBLE_BUBBLE_CHARS,
) -> list[str]:
    """Split plain text into short Zalo bubbles without adding semantics."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    chunks: list[str] = []
    current = ""

    def append_part(part: str) -> None:
        part = part.strip()
        if part:
            parts.append(part)

    def push(part: str) -> None:
        nonlocal current
        part = part.strip()
        if not part:
            return
        if not current:
            current = part
            return
        candidate = f"{current}\n\n{part}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = part

    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if len(paragraph) <= max_chars:
            append_part(paragraph)
            continue

        for piece in re.split(r"(?<=[.!?。！？])\s+|\n+", paragraph):
            piece = piece.strip()
            if len(piece) <= max_chars:
                append_part(piece)
                continue

            words = piece.split()
            segment = ""
            for word in words:
                if len(word) > max_chars:
                    append_part(segment)
                    segment = ""
                    for start in range(0, len(word), max_chars):
                        append_part(word[start : start + max_chars])
                    continue
                candidate = word if not segment else f"{segment} {word}"
                if len(candidate) <= max_chars:
                    segment = candidate
                    continue
                append_part(segment)
                segment = word
            append_part(segment)

    for part in parts:
        push(part)

    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Outbound: sendMessage / sendPhoto / sendSticker / sendVoice / sendChatAction
# ---------------------------------------------------------------------------


class ZaloBotSender:
    """Outbound calls to the Zalo Bot Platform.

    Use one instance per process (stateless; safe to share). The constructor
    accepts settings explicitly so tests can inject a fixture; production
    callers can use ``ZaloBotSender()`` to read ``get_settings()`` lazily.
    """

    def __init__(self, settings: Settings | None = None, *, bot_token: str | None = None) -> None:
        self._settings = settings or get_settings()
        self._bot_token = bot_token

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: Literal["markdown", "html"] | None = None,
        text_styles: list[dict[str, Any]] | None = None,
        quote_message_id: str | None = None,
    ) -> SendResult:
        """Send a text message, chunking long plain text into readable Zalo bubbles."""
        prepare_t0 = time.monotonic()
        text = text.strip()
        if not text:
            return SendResult(
                ok=False,
                error="text length must be 1..2000",
                telemetry=OutboundTelemetry(adapter="zalo_bot", result="rejected"),
            )
        if (parse_mode is not None or text_styles is not None) and len(text) > ZALO_MAX_TEXT_CHARS:
            return SendResult(
                ok=False,
                error="text length must be 1..2000",
                telemetry=OutboundTelemetry(adapter="zalo_bot", result="rejected"),
            )

        chunks = (
            [text]
            if parse_mode is not None or text_styles is not None
            else _split_long_plain_text(text)
        )
        # The splitters above already cap each chunk well under the API limit,
        # but guard defensively before sending — out-of-range text is rejected
        # upstream with a less specific error.
        for chunk in chunks:
            if not 1 <= len(chunk) <= ZALO_MAX_TEXT_CHARS:
                return SendResult(
                    ok=False,
                    error="text length must be 1..2000",
                    telemetry=OutboundTelemetry(adapter="zalo_bot", result="rejected"),
                )

        telemetry_base = OutboundTelemetry(
            adapter="zalo_bot",
            adapter_prepare_ms=int(round((time.monotonic() - prepare_t0) * 1000)),
        )
        resolved_token = (
            self._bot_token if self._bot_token is not None else self._settings.zalo_bot_token
        )
        if not resolved_token:
            return SendResult(
                ok=False,
                error="zalo_bot_token not configured",
                telemetry=telemetry_base.with_result("rejected"),
            )

        async def send_chunk(chunk: str) -> SendResult:
            body: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            # Rich-text offsets apply to the original string, so only attach them
            # to the single-message path where indices remain valid.
            if parse_mode is not None:
                body["parse_mode"] = parse_mode
            if text_styles is not None:
                body["text_styles"] = text_styles
            request_t0 = time.monotonic()
            result = _send_result(
                await _post(self._settings, "sendMessage", body, token=self._bot_token)
            )
            request_ms = int(round((time.monotonic() - request_t0) * 1000))
            return SendResult(
                ok=result.ok,
                msg_id=result.msg_id,
                error=result.error,
                raw=result.raw,
                error_class=result.error_class,
                telemetry=OutboundTelemetry(
                    adapter="zalo_bot",
                    provider_request_ms=request_ms,
                    provider_attempts=1,
                    chunk_count=1,
                    result="sent"
                    if result.ok
                    else ("transport_error" if result.error_class else "provider_error"),
                ),
            )

        return await _aggregate_chunked_send(
            chunks, send_chunk, telemetry_base=telemetry_base
        )

    async def send_photo(self, chat_id: str, photo: str, caption: str | None = None) -> SendResult:
        """Send an image by URL/path. ``caption`` is 1-2000 chars if provided."""
        if caption is not None and not 1 <= len(caption) <= 2000:
            return SendResult(ok=False, error="caption length must be 1..2000 when provided")
        body: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption is not None:
            body["caption"] = caption
        return _send_result(await _post(self._settings, "sendPhoto", body, token=self._bot_token))

    async def send_sticker(self, chat_id: str, sticker: str) -> SendResult:
        """Send a sticker by id from stickers.zaloapp.com."""
        return _send_result(
            await _post(
                self._settings,
                "sendSticker",
                {"chat_id": chat_id, "sticker": sticker},
                token=self._bot_token,
            )
        )

    async def send_voice(self, chat_id: str, voice_url: str) -> SendResult:
        """Send a ``.aac`` voice URL. 1-1 only — group chats are silently dropped upstream."""
        return _send_result(
            await _post(
                self._settings,
                "sendVoice",
                {"chat_id": chat_id, "voice_url": voice_url},
                token=self._bot_token,
            )
        )

    async def send_chat_action(self, chat_id: str, action: ChatAction) -> SendResult:
        """Show a transient status (``typing`` / ``upload_photo``) in the chat.

        Best-effort: callers should not fail the user-visible turn if this
        errors. Zalo's envelope for this method is ``{ok: true}`` only —
        ``message_id`` will always be ``None``.
        """
        envelope = await _post(
            self._settings,
            "sendChatAction",
            {"chat_id": chat_id, "action": action},
            token=self._bot_token,
        )
        # sendChatAction replies ``{ok: true}`` with no ``result``; ``_send_result``
        # reports ``msg_id=None`` for that shape, which is exactly what we want.
        return _send_result(envelope)

    async def send_buttons(
        self,
        chat_id: str,
        *,
        text: str,
        buttons: list[dict[str, Any]],
    ) -> SendResult:
        """Interactive buttons are an OA-template concept, not a Bot Platform method.

        Returning a clean not-supported result lets ``ZaloChannelSender`` forward
        ``send_buttons`` uniformly across channels without ``hasattr`` checks.
        """
        return SendResult(
            ok=False,
            error="interactive buttons not supported on bot channel",
            raw={"chat_id": chat_id, "text": text, "buttons": buttons},
        )

    async def send_media(
        self,
        chat_id: str,
        *,
        text: str,
        media_url: str,
        media_type: str = "image",
    ) -> SendResult:
        """Channel-uniform media send; Bot Platform only supports image via sendPhoto."""
        if media_type != "image":
            return SendResult(
                ok=False,
                error=f"media_type {media_type!r} not supported on bot channel",
            )
        return await self.send_photo(chat_id, media_url, caption=text or None)


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
        return _send_result(envelope)

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
        return _send_result(envelope)

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
        return _send_result(envelope)

    async def delete_webhook(self) -> SendResult:
        """Unregister the webhook. After this, ``getUpdates`` becomes available."""
        envelope = await _post(self._settings, "deleteWebhook", None)
        return _send_result(envelope)

    async def get_webhook_info(self) -> SendResult:
        """Return current webhook status. ``raw["result"]`` is the ``WebhookInfo`` payload."""
        envelope = await _post(self._settings, "getWebhookInfo", None)
        return _send_result(envelope)
