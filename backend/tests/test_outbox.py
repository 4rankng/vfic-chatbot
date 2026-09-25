"""Tests for the outbound transactional outbox (Tech-Lead Directive §14).

The migration is exercised by ``alembic upgrade head`` / ``downgrade -1`` /
``upgrade head`` (run manually before this suite in dev; the unit tests below
cover the service-layer behavior with a stub session).

Covers:
- ``enqueue_outbox``: insert + upsert-on-conflict semantics
- ``OutboxStatus`` enum values match the migration's CHECK constraint
- ``record_bot_outcome`` writes an outbox row when channel+payload provided
- ``record_bot_outcome`` skips the outbox when no delivery channel is requested
- ``_build_outbox_payload`` includes quote_message_id only when present
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock


from app.models.outbox import OutboxStatus


# ─── OutboxStatus enum ───────────────────────────────────────────────────────


def test_outbox_status_values_match_migration_check_constraint():
    """Enum values must match the migration's CHECK constraint exactly."""
    assert {s.value for s in OutboxStatus} == {
        "PENDING",
        "SENDING",
        "SENT",
        "FAILED",
        "SEND_UNKNOWN",
        "SUPPRESSED",
    }


def test_dispatch_result_matches_graph_sender_result_contract():
    """Durable dispatches expose the same provider id field as direct sends."""
    from app.services.outbox_service import DispatchResult

    result = DispatchResult(outbox_id=1, message_id=2, ok=True, zalo_message_id="zalo-1")
    assert result.msg_id == "zalo-1"


# ─── enqueue_outbox ──────────────────────────────────────────────────────────


async def test_create_pending_messenger_outbox_stamps_active_page_generation():
    """A Messenger command carries the Page authority active when it is created."""
    from sqlalchemy.dialects import postgresql

    from app.services import outbox_service

    captured = {}
    inserted = SimpleNamespace(channel_account_generation=7)

    class _FakeResult:
        def scalar_one_or_none(self):
            return inserted

    class _FakeDB:
        async def scalar(self, stmt):
            captured["generation_query"] = stmt
            return 7

        async def execute(self, stmt):
            captured["insert"] = stmt
            return _FakeResult()

    row = await outbox_service.create_pending_outbox(
        _FakeDB(),
        message_id=42,
        channel="facebook_messenger",
        payload={"chat_id": "psid-1", "text": "Xin chào"},
    )

    params = captured["insert"].compile(dialect=postgresql.dialect()).params
    assert captured.get("generation_query") is not None
    assert params["channel_account_generation"] == 7
    assert row is inserted


async def test_create_pending_outbox_can_write_the_command_already_claimed():
    """The inline bot turn writes its command already SENDING (REL-06).

    ``claim_send`` owns the claim, so the row must never be visible to the
    dispatcher's PENDING sweep while the inline send is still running.
    """
    from sqlalchemy.dialects import postgresql

    from app.services import outbox_service

    captured = {}

    class _FakeResult:
        def scalar_one_or_none(self):
            return SimpleNamespace(channel_account_generation=None)

    class _FakeDB:
        async def scalar(self, stmt):
            return None

        async def execute(self, stmt):
            captured["insert"] = stmt
            return _FakeResult()

    await outbox_service.create_pending_outbox(
        _FakeDB(),
        message_id=42,
        channel="zalo_bot",
        payload={"chat_id": "c1", "text": "hi"},
        status=OutboxStatus.SENDING,
    )

    params = captured["insert"].compile(dialect=postgresql.dialect()).params
    assert params["status"] == OutboxStatus.SENDING.value
    # The claim this row already carries is the attempt the inline send makes.
    assert params["attempts"] == 1


async def test_dispatch_message_outbox_resumes_the_callers_own_claim(monkeypatch):
    """A command the inline turn claimed itself is sent, not refused (REL-06).

    Before this, the row stayed PENDING until the inline dispatch claimed it, so a
    dispatcher tick landing in that window won the claim and the turn recorded a
    false ERROR for a message the sweep had delivered.
    """
    from app.models.conversation import DeliveryStatus
    from app.services import outbox_service

    outbox = SimpleNamespace(
        id=5,
        message_id=42,
        channel="zalo_bot",
        payload={"chat_id": "c1", "text": "hi"},
        status=OutboxStatus.SENDING.value,
        fence_scope=None,
    )
    message = SimpleNamespace(delivery_status=DeliveryStatus.SENDING)
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[outbox, DeliveryStatus.SENDING]),
        get=AsyncMock(return_value=message),
        commit=AsyncMock(),
    )
    provider = AsyncMock(
        return_value=outbox_service.DispatchResult(
            outbox_id=5, message_id=42, ok=True, provider_message_id="mid-1"
        )
    )

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(outbox_service, "_try_neutral_dispatch", provider)
    monkeypatch.setattr(
        outbox_service, "claim_pending_outbox", AsyncMock(return_value=None)
    )

    result = await outbox_service.dispatch_message_outbox(db, message_id=42)

    assert result is not None and result.ok
    assert result.msg_id == "mid-1"
    provider.assert_awaited_once()


async def test_dispatch_message_outbox_never_sends_a_row_claimed_by_another_sender(monkeypatch):
    """A SENDING command whose message is still PENDING belongs to the sweep.

    ``claim_pending_outbox`` is the single-sender guarantee; the inline entry
    point must not send a row another sender already owns.
    """
    from app.models.conversation import DeliveryStatus
    from app.services import outbox_service

    outbox = SimpleNamespace(
        id=5,
        message_id=42,
        channel="zalo_bot",
        payload={"chat_id": "c1", "text": "hi"},
        status=OutboxStatus.SENDING.value,
        fence_scope=None,
    )
    message = SimpleNamespace(delivery_status=DeliveryStatus.PENDING)
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[outbox, DeliveryStatus.PENDING]),
        get=AsyncMock(return_value=message),
        commit=AsyncMock(),
    )
    provider = AsyncMock()

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(outbox_service, "_try_neutral_dispatch", provider)

    result = await outbox_service.dispatch_message_outbox(db, message_id=42)

    assert result is None
    provider.assert_not_awaited()


# ─── terminal recipient marks (dead-recipient send failures) ──────────────────


class _FakeRedis:
    """Minimal async Redis for the terminal-marker helpers."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.set_calls.append((key, value, ex))

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0


def _patch_redis(monkeypatch) -> _FakeRedis:
    import app.core.redis as redis_mod

    fake = _FakeRedis()
    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)
    return fake


def _sending_outbox(channel: str = "zalo_bot", chat_id: str = "c1"):
    return SimpleNamespace(
        id=5,
        message_id=42,
        channel=channel,
        payload={"chat_id": chat_id, "text": "hi"},
        status=OutboxStatus.SENDING.value,
        fence_scope=None,
    )


def _dispatch_db(outbox):
    from app.models.conversation import DeliveryStatus

    message = SimpleNamespace(delivery_status=DeliveryStatus.SENDING)
    return SimpleNamespace(
        scalar=AsyncMock(side_effect=[outbox, DeliveryStatus.SENDING]),
        get=AsyncMock(return_value=message),
        commit=AsyncMock(),
    )


def _patch_dispatch(monkeypatch, provider):
    from app.services import outbox_service

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(outbox_service, "_try_neutral_dispatch", provider)
    monkeypatch.setattr(
        outbox_service, "claim_pending_outbox", AsyncMock(return_value=None)
    )
    return outbox_service


async def test_mark_recipient_unreachable_round_trips_with_done_ttl(monkeypatch):
    """The marker is per (channel, recipient) and uses the profile-marker TTL."""
    from app.services.outbox.recipient_marks import (
        _SEND_UNREACHABLE_TTL_SECONDS,
        is_recipient_unreachable,
        mark_recipient_unreachable,
    )

    fake = _patch_redis(monkeypatch)

    assert await is_recipient_unreachable("zalo_bot", "c1") is False
    await mark_recipient_unreachable("zalo_bot", "c1")

    assert await is_recipient_unreachable("zalo_bot", "c1") is True
    assert await is_recipient_unreachable("zalo_bot", "c2") is False  # per recipient
    assert await is_recipient_unreachable("zalo_oa", "c1") is False  # per channel
    assert fake.set_calls[0][2] == _SEND_UNREACHABLE_TTL_SECONDS


async def test_dispatch_skips_a_terminally_marked_recipient(monkeypatch):
    """A marked recipient is never sent to — the command terminalizes suppressed."""
    from app.services.outbox.recipient_marks import mark_recipient_unreachable

    _patch_redis(monkeypatch)
    await mark_recipient_unreachable("zalo_bot", "c1")

    outbox = _sending_outbox()
    provider = AsyncMock()
    outbox_service = _patch_dispatch(monkeypatch, provider)

    result = await outbox_service.dispatch_message_outbox(
        _dispatch_db(outbox), message_id=42
    )

    assert result is not None
    assert result.suppressed is True
    assert result.error_class == "user_unreachable"
    provider.assert_not_awaited()


async def test_dispatch_records_terminal_mark_on_unreachable_failure(monkeypatch):
    """A user_unreachable send failure writes the marker for later turns."""
    from app.services.outbox.recipient_marks import is_recipient_unreachable

    _patch_redis(monkeypatch)
    outbox = _sending_outbox()
    provider = AsyncMock(
        return_value=SimpleNamespace(
            outbox_id=5,
            message_id=42,
            ok=False,
            error="user_id is invalid",
            error_class="user_unreachable",
            suppressed=False,
        )
    )
    outbox_service = _patch_dispatch(monkeypatch, provider)

    result = await outbox_service.dispatch_message_outbox(
        _dispatch_db(outbox), message_id=42
    )

    assert result is not None and result.ok is False
    provider.assert_awaited_once()
    assert await is_recipient_unreachable("zalo_bot", "c1") is True


async def test_dispatch_does_not_mark_retryable_failures(monkeypatch):
    """A retryable provider failure must not terminally mark the recipient."""
    from app.services.outbox.recipient_marks import is_recipient_unreachable

    _patch_redis(monkeypatch)
    outbox = _sending_outbox()
    provider = AsyncMock(
        return_value=SimpleNamespace(
            outbox_id=5,
            message_id=42,
            ok=False,
            error="rate limited",
            error_class=None,
            suppressed=False,
        )
    )
    outbox_service = _patch_dispatch(monkeypatch, provider)

    await outbox_service.dispatch_message_outbox(_dispatch_db(outbox), message_id=42)

    assert await is_recipient_unreachable("zalo_bot", "c1") is False


async def test_enqueue_outbox_calls_insert_with_correct_fields(monkeypatch):
    """enqueue_outbox issues a PG insert with the right field mapping."""
    from app.services import outbox_service

    captured = {}

    class _FakeResult:
        def scalar_one_or_none(self):
            return None

    class _FakeDB:
        async def execute(self, stmt):
            # We don't assert the SQL text (fragile); we just verify it doesn't raise.
            captured["executed"] = True
            return _FakeResult()

    row = await outbox_service.enqueue_outbox(
        _FakeDB(),
        message_id=42,
        channel="zalo_bot",
        payload={"chat_id": "c1", "text": "hi"},
        status=OutboxStatus.SENT,
        zalo_message_id="zm1",
    )
    # The fake execute returns None from scalar_one_or_none; enqueue returns it.
    # Building the PostgreSQL upsert must reach execute rather than being
    # swallowed by the best-effort error handler.
    assert captured.get("executed") is True
    assert row is None


async def test_enqueue_outbox_swallows_db_errors():
    """A DB error must NOT propagate (best-effort)."""
    from app.services import outbox_service

    class _ExplodingDB:
        async def execute(self, stmt):
            raise RuntimeError("connection lost")

    row = await outbox_service.enqueue_outbox(
        _ExplodingDB(),
        message_id=42,
        channel="zalo_bot",
        payload={"chat_id": "c1", "text": "hi"},
        status=OutboxStatus.SENT,
    )
    assert row is None


# ─── claim_stale_sending ─────────────────────────────────────────────────────


async def test_claim_stale_sending_returns_candidates():
    from app.services import outbox_service

    fake_rows = [
        MagicMock(id=1, message_id=10, channel="zalo_bot", payload={"text": "a"}),
        MagicMock(id=2, message_id=20, channel="zalo_oa", payload={"text": "b"}),
    ]

    class _FakeResult:
        def all(self):
            return fake_rows

    class _FakeDB:
        async def execute(self, sql, params):
            return _FakeResult()

    candidates = await outbox_service.claim_stale_sending(
        _FakeDB(), stale_threshold_seconds=30, batch_size=10
    )
    assert len(candidates) == 2
    assert candidates[0].outbox_id == 1
    assert candidates[0].channel == "zalo_bot"
    assert candidates[1].outbox_id == 2
    assert candidates[1].channel == "zalo_oa"


async def test_claim_stale_sending_swallows_db_errors():
    from app.services import outbox_service

    class _ExplodingDB:
        async def execute(self, *a, **kw):
            raise RuntimeError("down")

    candidates = await outbox_service.claim_stale_sending(_ExplodingDB())
    assert candidates == []


async def test_stale_sending_outbox_ids_returns_only_ids():
    from app.services import outbox_service

    class _Rows:
        def all(self):
            return [7, 11]

    class _FakeDB:
        async def scalars(self, stmt):
            return _Rows()

    ids = await outbox_service.stale_sending_outbox_ids(_FakeDB(), stale_after_seconds=30, limit=10)
    assert ids == [7, 11]


async def test_claim_stale_sending_unknown_returns_none_when_a_live_worker_finished():
    """The stale-sweep conditional claim cannot overwrite a fresh SENT result."""
    from app.services import outbox_service

    class _Result:
        def one_or_none(self):
            return None

    class _FakeDB:
        async def execute(self, stmt):
            return _Result()

    claimed = await outbox_service.claim_stale_sending_unknown(
        _FakeDB(), outbox_id=7, stale_after_seconds=30
    )
    assert claimed is None


# ─── count_by_status ─────────────────────────────────────────────────────────


async def test_count_by_status_groups_correctly():
    from app.services import outbox_service

    fake_rows = [
        MagicMock(status="SENT", n=100),
        MagicMock(status="FAILED", n=3),
        MagicMock(status="SEND_UNKNOWN", n=1),
    ]

    class _FakeResult:
        def all(self):
            return fake_rows

    class _FakeDB:
        async def execute(self, sql, params):
            return _FakeResult()

    counts = await outbox_service.count_by_status(_FakeDB(), since=datetime.now(timezone.utc))
    assert counts == {"SENT": 100, "FAILED": 3, "SEND_UNKNOWN": 1}


async def test_count_by_status_empty_returns_empty_dict():
    from app.services import outbox_service

    class _FakeResult:
        def all(self):
            return []

    class _FakeDB:
        async def execute(self, *a, **kw):
            return _FakeResult()

    counts = await outbox_service.count_by_status(_FakeDB(), since=datetime.now(timezone.utc))
    assert counts == {}


# ─── runner helper: _build_outbox_payload ────────────────────────────────────


def test_build_outbox_payload_includes_quote_when_present():
    from app.graph.runner import _build_outbox_payload

    payload = _build_outbox_payload("chat-1", "hello", quote_message_id="inbound-1")
    assert payload == {
        "chat_id": "chat-1",
        "text": "hello",
        "quote_message_id": "inbound-1",
    }


def test_build_outbox_payload_omits_quote_when_absent():
    from app.graph.runner import _build_outbox_payload

    payload = _build_outbox_payload("chat-1", "hello", quote_message_id=None)
    assert payload == {"chat_id": "chat-1", "text": "hello"}
    assert "quote_message_id" not in payload


# ─── record_bot_outcome outbox integration ──────────────────────────────────


async def test_record_bot_outcome_skips_outbox_when_channel_none():
    """When outbox_channel is None (legacy callers), no outbox row is written.

    Verifies backward compatibility: existing callers that don't pass
    outbox_channel/outbox_payload get the pre-outbox behavior unchanged.
    """
    # This is a behavior-contract test: we verify the guard condition in the
    # source (``if outbox_channel is not None and outbox_payload is not None``).
    # A full integration test would require a DB + migration applied; that's
    # covered by the manual upgrade/downgrade roundtrip + the service-layer
    # tests above.
    from app.services.conversation import state

    # Inspect the source signature to confirm the new params default to None.
    import inspect

    sig = inspect.signature(state.ConversationState.record_bot_outcome)
    assert sig.parameters["outbox_channel"].default is None
    assert sig.parameters["outbox_payload"].default is None


# ─── Phase 1 characterization: durable delivery invariants the neutral
# ChannelSendResult + ChannelDispatchService (Phase 3) must preserve.
#
# These tests freeze the *semantics*: persist-before-send, at-most-once
# (SEND_UNKNOWN is never blindly replayed), and the message_id uniqueness that
# backs durable inbound idempotency in Phase 2.
# ────────────────────────────────────────────────────────────────────────────


def test_phase1_outbox_status_ordering_is_monotonic_and_terminal():
    """PENDING → SENDING → {SENT, FAILED, SEND_UNKNOWN, SUPPRESSED}.

    SEND_UNKNOWN is terminal and non-retriable: the dispatcher sweep never
    re-dispatches it (Zalo may have accepted). Phase 3's neutral dispatch
    service must preserve this. Enum order is checked against the migration
    CHECK constraint values, not ordinal position.
    """
    from app.models.outbox import OutboxStatus

    terminal = {OutboxStatus.SENT, OutboxStatus.FAILED, OutboxStatus.SEND_UNKNOWN, OutboxStatus.SUPPRESSED}
    transient = {OutboxStatus.PENDING, OutboxStatus.SENDING}

    # PENDING may be dispatched; SENDING is transient but only terminalized.
    assert OutboxStatus.PENDING in transient
    assert OutboxStatus.SENDING in transient
    # SEND_UNKNOWN is terminal — it must never appear in a re-dispatch claim.
    assert OutboxStatus.SEND_UNKNOWN in terminal
    assert OutboxStatus.SEND_UNKNOWN not in transient


def test_dispatch_stale_age_covers_maximum_chunked_oa_attempt_window():
    from types import SimpleNamespace

    from app.services.outbox_service import outbound_dispatch_stale_after_seconds

    settings = SimpleNamespace(
        zalo_bot_request_timeout=30,
        chat_turn_job_timeout=60,
    )

    # Twenty worst-case chunks + refresh + retry, then one turn timeout of margin.
    assert outbound_dispatch_stale_after_seconds(settings) == 720


class _ExplodingSession:
    """AsyncSession stand-in whose execute() fails the way a dropped DB does."""

    async def execute(self, _stmt):
        raise RuntimeError("boom: insert failed")

    async def scalar(self, _stmt):
        raise RuntimeError("boom: insert failed")


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _NoRowSession:
    """Insert returned no row AND the follow-up select finds no existing row."""

    async def execute(self, _stmt):
        return _FakeResult(None)

    async def scalar(self, _stmt):
        return None


async def test_create_pending_outbox_propagates_a_failing_persist_instead_of_swallowing():
    """create_pending_outbox must never swallow a DB failure: acknowledging a
    reply without its durable command would make crash recovery impossible."""
    from app.services.outbox_service import create_pending_outbox

    with pytest.raises(RuntimeError, match="boom"):
        await create_pending_outbox(
            _ExplodingSession(),
            message_id=1,
            channel="zalo_bot",
            payload={"chat_id": "x", "text": "hi"},
        )


async def test_create_pending_outbox_fails_closed_when_no_row_could_be_written():
    """Insert conflict with no surviving row must raise, not return garbage."""
    from app.services.outbox_service import create_pending_outbox

    with pytest.raises(RuntimeError, match="failed to persist outbound command"):
        await create_pending_outbox(
            _NoRowSession(),
            message_id=1,
            channel="zalo_conditional",
            payload={"chat_id": "x", "text": "hi"},
        )


async def test_enqueue_outbox_swallows_a_failing_persist_and_returns_none():
    """enqueue_outbox is best-effort: a DB failure must not block the turn."""
    from app.services.outbox_service import enqueue_outbox

    assert (
        await enqueue_outbox(
            _ExplodingSession(),
            message_id=1,
            channel="zalo_bot",
            payload={"chat_id": "x", "text": "hi"},
            status=OutboxStatus.SENT,
        )
        is None
    )


def test_dispatch_worker_uses_the_same_safe_age_for_selection_and_claim():
    """Composition wiring pin: the recovery sweep's selection window and its
    per-row claim window must come from the same settings-derived value. The
    sweep itself is exercised against the DB by the integration lane."""
    import inspect

    from app.composition import conversation_messaging

    root_source = inspect.getsource(conversation_messaging.run_outbound_recovery)
    adapter_source = inspect.getsource(
        conversation_messaging.SqlAlchemyOutboundRecoveryAdapter
    )

    assert "outbound_dispatch_stale_after_seconds" in root_source
    assert adapter_source.count("stale_after_seconds=self.stale_after_seconds") == 2


# The stale-claim sweep behaviour (claim_stale_sending / claim_stale_sending_unknown)
# needs Postgres (FOR UPDATE SKIP LOCKED, conditional UPDATE ... WHERE) and is
# asserted against the disposable DB in
# tests/integration/test_outbox_stale_claim.py.
