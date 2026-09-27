"""Unit tests for the Zalo Bot Platform service layer.

Mocks ``_post`` (the shared transport) so tests stay fast and offline.
One end-to-end test exercises ``httpx.AsyncClient.post`` directly to
lock in the URL contract (``{base}/bot{TOKEN}/{method}`` with the token
in the path, NOT a header) — that is the one piece callers cannot
change silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.core.config import Settings
from app.services import zalo_bot_service as svc

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    """Settings wired with a fake Bot Platform token + base URL.

    Uses the constructor directly rather than mutating the cached
    ``get_settings()`` so tests cannot leak env values into other tests.
    """
    return Settings(
        app_env="development",
        zalo_bot_token="test-token-xyz",
        zalo_bot_api_base="https://bot-api.zaloplatforms.com",
        zalo_bot_request_timeout=5,
    )


@pytest.fixture
def unconfigured_settings() -> Settings:
    """Settings with an empty Bot Platform token — sender/admin should no-op."""
    return Settings(app_env="development", zalo_bot_token="")


@dataclass
class _Captured:
    """Records every call to ``_post`` for assertion in test bodies."""

    calls: list[tuple[str, dict[str, Any] | None]]


def _patch_post(monkeypatch: pytest.MonkeyPatch, envelopes: list[dict[str, Any]]):
    """Patch ``_post`` so each successive call returns the next canned envelope.

    Returns the ``_Captured`` instance the test can introspect. If ``envelopes``
    is empty, defaults to a single ok-with-empty-result envelope so the
    caller can assert the method's projection without caring about shape.
    """
    cap = _Captured(calls=[])

    async def fake_post(self, method: str, body: dict[str, Any] | None, **_: Any):
        cap.calls.append((method, body))
        if envelopes:
            return envelopes.pop(0)
        return {"ok": True, "result": {}}

    monkeypatch.setattr(svc, "_post", fake_post)
    return cap


# ---------------------------------------------------------------------------
# URL contract — end-to-end through httpx
# ---------------------------------------------------------------------------


async def test_url_contract_token_in_path_not_header(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """Lock in the URL shape: ``{base}/bot{TOKEN}/{method}``, token NEVER in a header."""
    captured: dict[str, Any] = {}

    class _FakeResp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"ok": True, "result": {"message_id": "m1", "date": 1700000000000}}

    class _FakeClient:
        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
            **kw: Any,
        ) -> _FakeResp:
            captured["url"] = url
            captured["headers"] = headers or {}
            # The httpx kwarg is named ``json``; alias it to ``body`` locally
            # so we don't shadow the stdlib ``json`` module elsewhere in the file.
            captured["body"] = json
            return _FakeResp()

    from tests.helpers.http_fake import register_fake_client

    register_fake_client("zalo_bot", _FakeClient())
    sender = svc.ZaloBotSender(settings=settings)
    result = await sender.send_message("chat-1", "hello")

    assert result.ok is True
    assert result.msg_id == "m1"
    assert captured["url"] == "https://bot-api.zaloplatforms.com/bottest-token-xyz/sendMessage"
    # The token MUST NOT leak into any header (auth is via URL path on this platform).
    assert all("test-token-xyz" not in str(v) for v in captured["headers"].values())
    assert captured["body"] == {"chat_id": "chat-1", "text": "hello"}


# ---------------------------------------------------------------------------
# Missing-token path
# ---------------------------------------------------------------------------


async def test_sender_missing_token_no_op(unconfigured_settings: Settings) -> None:
    """No token configured → returns ok=False with a clear error, never raises."""
    sender = svc.ZaloBotSender(settings=unconfigured_settings)
    result = await sender.send_message("chat-1", "hi")
    assert result.ok is False
    assert "not configured" in (result.error or "")
    assert result.msg_id is None
    assert result.telemetry is not None
    assert result.telemetry.provider_attempts == 0
    assert result.telemetry.result == "rejected"


async def test_admin_missing_token_no_op(unconfigured_settings: Settings) -> None:
    admin = svc.ZaloBotAdminClient(settings=unconfigured_settings)
    for coro in (
        admin.get_me(),
        admin.get_updates(),
        admin.set_webhook("https://example.com/hook", "x" * 16),
        admin.delete_webhook(),
        admin.get_webhook_info(),
    ):
        result = await coro
        assert result.ok is False
        assert "not configured" in (result.error or "")


# ---------------------------------------------------------------------------
# Sender methods
# ---------------------------------------------------------------------------


async def test_send_message_happy_path(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    cap = _patch_post(
        monkeypatch, [{"ok": True, "result": {"message_id": "m-42", "date": 1700000000}}]
    )
    sender = svc.ZaloBotSender(settings=settings)

    result = await sender.send_message("chat-1", "hello")

    assert result.ok is True
    assert result.msg_id == "m-42"
    assert cap.calls == [("sendMessage", {"chat_id": "chat-1", "text": "hello"})]
    assert result.telemetry is not None
    assert result.telemetry.adapter == "zalo_bot"
    assert result.telemetry.provider_attempts == 1
    assert result.telemetry.chunk_count == 1
    assert result.telemetry.result == "sent"


async def test_send_message_splits_long_plain_text_into_visible_bubbles(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    cap = _patch_post(
        monkeypatch,
        [
            {"ok": True, "result": {"message_id": "m-1", "date": 1700000000}},
            {"ok": True, "result": {"message_id": "m-2", "date": 1700000001}},
            {"ok": True, "result": {"message_id": "m-3", "date": 1700000002}},
            {"ok": True, "result": {"message_id": "m-4", "date": 1700000003}},
        ],
    )
    sender = svc.ZaloBotSender(settings=settings)
    long_reply = (
        "Cảm ơn Dũng đã hỏi nhé! Dựa trên thông tin mình có, mình chia sẻ cụ thể cho bạn:\n\n"
        "Công việc chính tại LG Display là sản xuất và kiểm tra màn hình các sản phẩm như "
        "tivi, máy tính, điện thoại.\n\n"
        "Hàng ngày bạn sẽ làm việc theo ca luân phiên:\n"
        "- Ca ngày: 08:00 - 20:00\n"
        "- Ca đêm: 20:00 - 08:00\n\n"
        "Lịch kíp: 4 ngày ca ngày -> nghỉ 2 ngày -> 4 ngày ca đêm -> nghỉ 2 ngày -> lặp lại.\n\n"
        "Công việc cụ thể bao gồm các công đoạn trên dây chuyền sản xuất và kiểm tra chất lượng "
        "sản phẩm màn hình.\n\n"
        "Về địa chỉ văn phòng VFIC Hải Phòng, mình chưa có thông tin cụ thể trong dữ liệu lúc này. "
        "Bạn có thể gọi hotline VFIC để được cung cấp địa chỉ chính xác nhé.\n\n"
        "Bạn còn câu hỏi gì thêm không, hay đã sẵn sàng đến nộp hồ sơ rồi?\n\n"
        + ("Thông tin bổ sung " * 47).strip()
        + "\n\n"
        + ("Chi tiết thêm " * 60).strip()
    )

    result = await sender.send_message("chat-1", long_reply)

    assert result.ok is True
    assert result.msg_id == "m-1"
    assert len(cap.calls) >= 2
    assert [call[0] for call in cap.calls] == ["sendMessage"] * len(cap.calls)
    sent_texts = [(call[1] or {})["text"] for call in cap.calls]
    assert all(1 <= len(text) <= svc.ZALO_VISIBLE_BUBBLE_CHARS for text in sent_texts)
    assert "\n\n".join(sent_texts) == long_reply


async def test_send_message_split_failure_reports_partial_delivery(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    cap = _patch_post(
        monkeypatch,
        [
            {"ok": True, "result": {"message_id": "m-1", "date": 1700000000}},
            {"ok": False, "description": "rate limited"},
        ],
    )
    sender = svc.ZaloBotSender(settings=settings)
    long_reply = "Đoạn một " + ("rất dài " * 125) + "\n\nĐoạn hai " + ("cũng dài " * 111)

    result = await sender.send_message("chat-1", long_reply)

    assert result.ok is False
    assert result.msg_id == "m-1"
    assert "chunk 2/" in (result.error or "")
    assert "rate limited" in (result.error or "")
    assert len(cap.calls) == 2
    assert result.telemetry is not None
    assert result.telemetry.chunk_count == 2
    assert result.telemetry.result == "provider_error"
    # REL-01: bubble 1 reached the candidate, so the aggregate is at-most-once.
    # A null error_class here meant "retryable", which made the reconcile sweep
    # re-answer the candidate — including the bubble they had already read. The
    # ambiguous class is what routes the row to SEND_UNKNOWN instead.
    assert result.partial is True
    assert result.error_class == "unknown"


async def test_visible_bubble_size_stays_under_provider_cap() -> None:
    """Bubbles split below the provider's documented 2000-char per-message cap."""
    assert svc.ZALO_VISIBLE_BUBBLE_CHARS < svc.ZALO_MAX_TEXT_CHARS
    # A long answer becomes a few sequential POSTs, not the many the old 420
    # split produced.
    assert svc.ZALO_VISIBLE_BUBBLE_CHARS >= 1000


async def test_split_never_exceeds_provider_cap_on_giant_input() -> None:
    """No split chunk may exceed the provider cap, even for adversarial input."""
    giant = "từ " * 5000  # no punctuation, one giant run of words and spaces
    chunks = svc._split_long_plain_text(giant)

    assert len(chunks) >= 2
    assert all(1 <= len(chunk) <= svc.ZALO_VISIBLE_BUBBLE_CHARS for chunk in chunks)
    assert all(len(chunk) <= svc.ZALO_MAX_TEXT_CHARS for chunk in chunks)


async def test_send_message_invalid_recipient_is_stamped_unreachable(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """``user_id is invalid`` is a permanent recipient failure, not retryable."""
    _patch_post(monkeypatch, [{"ok": False, "description": "user_id is invalid"}])
    result = await svc.ZaloBotSender(settings=settings).send_message("chat-bad", "hi")

    assert result.ok is False
    assert result.error_class == "user_unreachable"


async def test_send_message_other_rejection_stays_retryable(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """A non-recipient rejection keeps a null class so the reconciler may retry."""
    _patch_post(monkeypatch, [{"ok": False, "description": "rate limited"}])
    result = await svc.ZaloBotSender(settings=settings).send_message("chat-1", "hi")

    assert result.ok is False
    assert result.error_class is None


async def test_send_message_with_optional_fields(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    cap = _patch_post(
        monkeypatch, [{"ok": True, "result": {"message_id": "m-43", "date": 1700000001}}]
    )
    sender = svc.ZaloBotSender(settings=settings)

    result = await sender.send_message(
        "chat-1",
        "*hello*",
        parse_mode="markdown",
        text_styles=[{"start": 0, "len": 5, "st": ["b"]}],
    )

    assert result.ok is True
    assert cap.calls[0][0] == "sendMessage"
    body = cap.calls[0][1] or {}
    assert body["parse_mode"] == "markdown"
    assert body["text_styles"] == [{"start": 0, "len": 5, "st": ["b"]}]
    # parse_mode and text_styles must NOT be sent when not provided (avoiding
    # an empty field that the API might interpret as a request to clear styles).
    cap = _patch_post(
        monkeypatch, [{"ok": True, "result": {"message_id": "m-44", "date": 1700000002}}]
    )
    result = await sender.send_message("chat-1", "plain")
    body = cap.calls[0][1] or {}
    assert "parse_mode" not in body
    assert "text_styles" not in body


async def test_send_message_length_validation(settings: Settings) -> None:
    """Pre-flight length check; never makes the HTTP call for invalid input."""
    sender = svc.ZaloBotSender(settings=settings)
    assert (await sender.send_message("chat-1", "")).ok is False
    assert (await sender.send_message("chat-1", "x" * 2001)).ok is False


async def test_send_photo_happy_path(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    cap = _patch_post(
        monkeypatch, [{"ok": True, "result": {"message_id": "p-1", "date": 1700000000}}]
    )
    result = await svc.ZaloBotSender(settings=settings).send_photo(
        "chat-1", "https://x/y.jpg", "look"
    )
    assert result.ok is True
    assert cap.calls == [
        ("sendPhoto", {"chat_id": "chat-1", "photo": "https://x/y.jpg", "caption": "look"})
    ]


async def test_send_photo_no_caption(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    cap = _patch_post(
        monkeypatch, [{"ok": True, "result": {"message_id": "p-2", "date": 1700000000}}]
    )
    await svc.ZaloBotSender(settings=settings).send_photo("chat-1", "https://x/y.jpg")
    body = cap.calls[0][1] or {}
    assert "caption" not in body


async def test_send_photo_caption_length_validation(settings: Settings) -> None:
    sender = svc.ZaloBotSender(settings=settings)
    assert (await sender.send_photo("chat-1", "https://x/y.jpg", "")).ok is False
    assert (await sender.send_photo("chat-1", "https://x/y.jpg", "x" * 2001)).ok is False


async def test_send_sticker_happy_path(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    cap = _patch_post(
        monkeypatch, [{"ok": True, "result": {"message_id": "s-1", "date": 1700000000}}]
    )
    result = await svc.ZaloBotSender(settings=settings).send_sticker("chat-1", "sticker-id-abc")
    assert result.ok is True
    assert cap.calls == [("sendSticker", {"chat_id": "chat-1", "sticker": "sticker-id-abc"})]


async def test_send_voice_happy_path(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    cap = _patch_post(
        monkeypatch, [{"ok": True, "result": {"message_id": "v-1", "date": 1700000000}}]
    )
    result = await svc.ZaloBotSender(settings=settings).send_voice("chat-1", "https://x/y.aac")
    assert result.ok is True
    assert cap.calls == [("sendVoice", {"chat_id": "chat-1", "voice_url": "https://x/y.aac"})]


async def test_send_chat_action_happy_path(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """sendChatAction envelope is {ok:true} only — no result.message_id."""
    cap = _patch_post(monkeypatch, [{"ok": True}])
    result = await svc.ZaloBotSender(settings=settings).send_chat_action("chat-1", "typing")
    assert result.ok is True
    assert result.msg_id is None  # always None for chat actions
    assert cap.calls == [("sendChatAction", {"chat_id": "chat-1", "action": "typing"})]


async def test_send_chat_action_upload_photo(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """``upload_photo`` is the second documented action; passes through verbatim."""
    cap = _patch_post(monkeypatch, [{"ok": True}])
    result = await svc.ZaloBotSender(settings=settings).send_chat_action("chat-1", "upload_photo")
    assert result.ok is True
    assert cap.calls[0][1] == {"chat_id": "chat-1", "action": "upload_photo"}


async def test_send_message_error_envelope(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """ok=false: msg_id stays None, error reflects description."""
    _patch_post(monkeypatch, [{"ok": False, "error_code": 400, "description": "chat not found"}])
    result = await svc.ZaloBotSender(settings=settings).send_message("chat-bad", "hi")
    assert result.ok is False
    assert result.msg_id is None
    assert "chat not found" in (result.error or "")


# ---------------------------------------------------------------------------
# Admin methods
# ---------------------------------------------------------------------------


async def test_get_me_happy_path(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    """getMe success → msg_id carries the bot id (so a quick liveness check works)."""
    cap = _patch_post(
        monkeypatch,
        [
            {
                "ok": True,
                "result": {
                    "id": "1459232241454765289",
                    "account_name": "bot.VDKyGxQvc",
                    "account_type": "BASIC",
                    "can_join_groups": False,
                },
            }
        ],
    )
    result = await svc.ZaloBotAdminClient(settings=settings).get_me()
    assert result.ok is True
    assert result.msg_id == "1459232241454765289"
    assert cap.calls == [("getMe", None)]


async def test_get_me_malformed_envelope(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """Missing required field → returns ok=False rather than crashing the caller."""
    # No ``id`` → malformed envelope (other fields are optional fallbacks).
    _patch_post(monkeypatch, [{"ok": True, "result": {"account_name": "only-name"}}])
    result = await svc.ZaloBotAdminClient(settings=settings).get_me()
    assert result.ok is False
    assert "malformed" in (result.error or "")


async def test_get_updates_with_timeout(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    cap = _patch_post(monkeypatch, [{"ok": True, "result": [{"update_id": 1}]}])
    result = await svc.ZaloBotAdminClient(settings=settings).get_updates(timeout=10)
    assert result.ok is True
    # Zalo's API expects a STRING for timeout (per docs); we stringify defensively.
    assert cap.calls == [("getUpdates", {"timeout": "10"})]


async def test_get_updates_no_timeout(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    cap = _patch_post(monkeypatch, [{"ok": True, "result": []}])
    await svc.ZaloBotAdminClient(settings=settings).get_updates()
    # Body must be a dict even when no timeout — _post rejects falsy body with None.
    assert cap.calls[0][1] == {}


async def test_set_webhook_validates_secret_length(settings: Settings) -> None:
    """Client-side length check; the API would also reject but failing here is clearer."""
    admin = svc.ZaloBotAdminClient(settings=settings)
    short = await admin.set_webhook("https://example.com/hook", "short")
    assert short.ok is False
    assert "secret_token" in (short.error or "")
    long = await admin.set_webhook("https://example.com/hook", "x" * 257)
    assert long.ok is False


async def test_set_webhook_happy_path(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    cap = _patch_post(
        monkeypatch,
        [{"ok": True, "result": {"url": "https://example.com/hook", "updated_at": 1700000000000}}],
    )
    result = await svc.ZaloBotAdminClient(settings=settings).set_webhook(
        "https://example.com/hook", "x" * 16
    )
    assert result.ok is True
    assert cap.calls == [
        ("setWebhook", {"url": "https://example.com/hook", "secret_token": "x" * 16})
    ]


async def test_delete_webhook_happy_path(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    cap = _patch_post(
        monkeypatch, [{"ok": True, "result": {"url": "", "updated_at": 1700000000000}}]
    )
    result = await svc.ZaloBotAdminClient(settings=settings).delete_webhook()
    assert result.ok is True
    assert cap.calls == [("deleteWebhook", None)]


async def test_get_webhook_info_happy_path(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _patch_post(
        monkeypatch, [{"ok": True, "result": {"url": "https://example.com/hook", "updated_at": 1}}]
    )
    result = await svc.ZaloBotAdminClient(settings=settings).get_webhook_info()
    assert result.ok is True


# ---------------------------------------------------------------------------
# Envelope projection — _send_result
# ---------------------------------------------------------------------------


async def test_send_result_handles_non_dict_result() -> None:
    """Admin/chat-action envelopes carry a non-dict ``result`` (or none at all);
    ``_send_result`` must not crash and must yield ``msg_id=None`` + ``ok=True``.

    This is the path the admin methods and ``send_chat_action`` now rely on
    instead of inlining their own ok/error tail.
    """
    list_result = svc._send_result({"ok": True, "result": [{"update_id": 1}]})
    assert list_result.ok is True and list_result.msg_id is None

    missing_result = svc._send_result({"ok": True})
    assert missing_result.ok is True and missing_result.msg_id is None

    scalar_result = svc._send_result({"ok": True, "result": "unexpected"})
    assert scalar_result.ok is True and scalar_result.msg_id is None


async def test_send_result_failure_uses_description_or_error_code() -> None:
    """The failure branch is shared by every sender + admin method now."""
    assert svc._send_result({"ok": False, "description": "boom"}).error == "boom"
    assert svc._send_result({"ok": False, "error_code": 429}).error == "429"
    assert svc._send_result({"ok": False}).error == "unknown error"


# ---------------------------------------------------------------------------
# Chunked-send aggregation — _aggregate_chunked_send
# ---------------------------------------------------------------------------


async def test_aggregate_chunked_send_collects_first_id_and_envelope_trail() -> None:
    """A clean multi-chunk run returns the first msg_id and every raw envelope."""

    async def send_chunk(chunk: str) -> svc.SendResult:
        return svc.SendResult(ok=True, msg_id=f"id-{chunk}", raw={"text": chunk})

    result = await svc._aggregate_chunked_send(["a", "b", "c"], send_chunk)
    assert result.ok is True
    assert result.msg_id == "id-a"  # first wins
    assert result.raw == {
        "chunks": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
        "message_ids": ["id-a", "id-b", "id-c"],
    }


async def test_aggregate_chunked_send_short_circuits_on_first_failure() -> None:
    """A failed chunk stops the run with a chunk-indexed error and the partial trail."""
    sent: list[str] = []

    async def send_chunk(chunk: str) -> svc.SendResult:
        sent.append(chunk)
        if chunk == "b":
            return svc.SendResult(ok=False, error="upstream rejected", raw={"text": "b"})
        return svc.SendResult(ok=True, msg_id=f"id-{chunk}", raw={"text": chunk})

    result = await svc._aggregate_chunked_send(["a", "b", "c"], send_chunk)
    assert result.ok is False
    assert result.error == "chunk 2/3 failed: upstream rejected"
    assert result.msg_id == "id-a"  # collected before the failure
    assert sent == ["a", "b"]  # 'c' never sent
    assert result.raw == {
        "chunks": [{"text": "a"}, {"text": "b"}],
        "message_ids": ["id-a"],
    }


async def test_aggregate_chunked_send_marks_partial_delivery_at_most_once() -> None:
    """Bubble 1 delivered + bubble 2 rejected is a PARTIAL delivery (REL-01).

    The candidate already saw bubble 1, so the aggregate must be at-most-once:
    it keeps the delivered bubble's id and promotes the definite rejection to an
    ambiguous class, which is what the delivery-state machine routes to
    ``SEND_UNKNOWN``. A bare retryable ``FAILED`` here is what made the reconcile
    sweep answer the candidate twice.
    """
    from app.shared.application.outbound import is_ambiguous_send

    async def send_chunk(chunk: str) -> svc.SendResult:
        if chunk == "b":
            return svc.SendResult(ok=False, error="upstream rejected")
        return svc.SendResult(ok=True, msg_id=f"id-{chunk}")

    result = await svc._aggregate_chunked_send(["a", "b"], send_chunk)

    assert result.ok is False
    assert result.partial is True
    assert result.msg_id == "id-a"
    assert result.error_class == "unknown"
    assert is_ambiguous_send(result.error_class, ok=result.ok) is True


async def test_aggregate_chunked_send_keeps_a_transport_class_on_partial_delivery() -> None:
    """A partial delivery that failed ambiguously keeps its own class.

    ``read_timeout`` is already at-most-once; rewriting it would lose the reason
    the failed chunk produced.
    """

    async def send_chunk(chunk: str) -> svc.SendResult:
        if chunk == "b":
            return svc.SendResult(ok=False, error="timeout", error_class="read_timeout")
        return svc.SendResult(ok=True, msg_id="id-a")

    result = await svc._aggregate_chunked_send(["a", "b"], send_chunk)

    assert result.partial is True
    assert result.error_class == "read_timeout"


async def test_aggregate_chunked_send_all_bubbles_failed_stays_retryable() -> None:
    """Nothing was delivered → the failure keeps its own class, so recovery runs.

    An answer the candidate never saw is a genuinely lost turn; it must stay a
    retryable ``FAILED`` rather than being suppressed as a partial delivery.
    """
    from app.shared.application.outbound import is_ambiguous_send

    async def send_chunk(chunk: str) -> svc.SendResult:
        return svc.SendResult(ok=False, error="upstream rejected")

    result = await svc._aggregate_chunked_send(["a", "b"], send_chunk)

    assert result.ok is False
    assert result.partial is False
    assert result.msg_id is None
    assert result.error_class is None
    assert is_ambiguous_send(result.error_class, ok=result.ok) is False


async def test_aggregate_chunked_send_handles_ok_without_msg_id() -> None:
    """Successful chunks without a msg_id (ack-only envelopes) don't populate message_ids."""

    async def send_chunk(chunk: str) -> svc.SendResult:
        return svc.SendResult(ok=True, raw={"ack": chunk})

    result = await svc._aggregate_chunked_send(["x"], send_chunk)
    assert result.ok is True
    assert result.msg_id is None
    assert result.raw == {"chunks": [{"ack": "x"}], "message_ids": []}


# ---------------------------------------------------------------------------
# Transport-level error handling
# ---------------------------------------------------------------------------


async def test_post_transport_error_returns_envelope(settings: Settings) -> None:
    """Network/HTTP exception must surface as ``ok=False``, never raise."""
    from tests.helpers.http_fake import FakeHttpClient, register_fake_client

    fake = FakeHttpClient(side_effect=RuntimeError("boom"))
    register_fake_client("zalo_bot", fake)
    result = await svc.ZaloBotSender(settings=settings).send_message("chat-1", "hi")
    assert result.ok is False
    assert "boom" in (result.error or "")


async def test_post_non_json_envelope(settings: Settings) -> None:
    """Non-dict JSON (e.g. a bare list) is treated as a malformed envelope."""
    from tests.helpers.http_fake import FakeHttpClient, register_fake_client

    fake = FakeHttpClient(responses=[[1, 2, 3]])
    register_fake_client("zalo_bot", fake)
    result = await svc.ZaloBotSender(settings=settings).send_message("chat-1", "hi")
    assert result.ok is False
    assert "non-JSON" in (result.error or "") or "missing 'ok'" in (result.error or "")


async def test_post_missing_ok_field(settings: Settings) -> None:
    """``{}`` (no ``ok`` key) → malformed envelope error path."""
    from tests.helpers.http_fake import FakeHttpClient, register_fake_client

    fake = FakeHttpClient(responses=[{"weird": "shape"}])
    register_fake_client("zalo_bot", fake)
    result = await svc.ZaloBotSender(settings=settings).send_message("chat-1", "hi")
    assert result.ok is False
    assert "missing 'ok'" in (result.error or "")


# ---------------------------------------------------------------------------
# Re-exports / module surface
# ---------------------------------------------------------------------------


async def test_public_api_surface() -> None:
    """Lock in the names callers are allowed to import — changes here are breaking.

    Compare string names (what ``dir()`` returns) to string names, not class
    objects — a class-vs-string mismatch silently fails the ``<=`` check.
    """
    names = {n for n in dir(svc) if not n.startswith("_")}
    assert {
        "ZaloBotSender",
        "ZaloBotAdminClient",
        "SendResult",
        "BotInfo",
        "WebhookInfo",
    } <= names


# ---------------------------------------------------------------------------
# Verbatim rendering — markdown must not reach the user
# ---------------------------------------------------------------------------


async def test_send_message_flattens_markdown_to_plain_text(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """Zalo renders text verbatim: emphasis markup is dropped and links keep
    their target as bare text (clients auto-link URLs)."""
    cap = _patch_post(monkeypatch, [{"ok": True, "result": {"message_id": "m-md"}}])

    result = await svc.ZaloBotSender(settings=settings).send_message(
        "chat-1",
        "Xin chào! Hiện **đặt lại mật khẩu** chỉ hỗ trợ trên "
        "[Zalo OA TingTing](https://zalo.me/3383849659955472174)",
    )

    assert result.ok is True
    _, body = cap.calls[0]
    assert body["text"] == (
        "Xin chào! Hiện đặt lại mật khẩu chỉ hỗ trợ trên "
        "Zalo OA TingTing: https://zalo.me/3383849659955472174"
    )


async def test_send_message_parse_mode_opt_out_skips_flattening(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """A caller that opted into parse_mode owns its formatting and passes as-is."""
    cap = _patch_post(monkeypatch, [{"ok": True, "result": {"message_id": "m-pm"}}])

    await svc.ZaloBotSender(settings=settings).send_message(
        "chat-1", "**bold** stays", parse_mode="markdown"
    )

    _, body = cap.calls[0]
    assert body["text"] == "**bold** stays"
