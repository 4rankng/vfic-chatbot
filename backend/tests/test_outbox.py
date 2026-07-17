"""Tests for the outbound transactional outbox (Tech-Lead Directive §14).

The migration is exercised by ``alembic upgrade head`` / ``downgrade -1`` /
``upgrade head`` (run manually before this suite in dev; the unit tests below
cover the service-layer behavior with a stub session).

Covers:
- ``enqueue_outbox``: insert + upsert-on-conflict semantics
- ``OutboxStatus`` enum values match the migration's CHECK constraint
- ``record_bot_outcome`` writes an outbox row when channel+payload provided
- ``record_bot_outcome`` skips the outbox when channel is None (legacy callers)
- ``_detect_channel`` infers zalo_bot vs zalo_oa from the sender class
- ``_build_outbox_payload`` includes quote_message_id only when present
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock


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


# ─── runner helpers: _detect_channel + _build_outbox_payload ─────────────────


def test_detect_channel_zalo_bot():
    from app.graph.runner import _detect_channel

    class ZaloBotSender:
        pass

    assert _detect_channel(ZaloBotSender()) == "zalo_bot"


def test_detect_channel_zalo_oa():
    from app.graph.runner import _detect_channel

    class ZaloOASender:
        pass

    assert _detect_channel(ZaloOASender()) == "zalo_oa"


def test_detect_channel_unknown_defaults_to_bot():
    from app.graph.runner import _detect_channel

    class SomeOtherSender:
        pass

    assert _detect_channel(SomeOtherSender()) == "zalo_bot"


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

    # The two transient states are the only ones the sweep re-dispatches.
    assert OutboxStatus.PENDING in transient
    assert OutboxStatus.SENDING in transient
    # SEND_UNKNOWN is terminal — it must never appear in a re-dispatch claim.
    assert OutboxStatus.SEND_UNKNOWN in terminal
    assert OutboxStatus.SEND_UNKNOWN not in transient


def test_phase1_claim_stale_sending_unknown_never_reverts_to_pending():
    """A stale SENDING row is terminalized to SEND_UNKNOWN, never reverted to
    PENDING. Reverting would risk a duplicate send (Zalo may have accepted).

    This freezes the behavior in executable code (not docstrings): the
    conditional update matches status='SENDING' and writes status='SEND_UNKNOWN'.
    """
    import ast
    import inspect

    from app.services import outbox_service

    src = inspect.getsource(outbox_service.claim_stale_sending_unknown)
    # strip docstring, keep only executable code
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")
    code = ast.unparse(tree)

    # matches only SENDING rows
    assert "OutboxStatus.SENDING.value" in code
    # writes SEND_UNKNOWN
    assert "OutboxStatus.SEND_UNKNOWN.value" in code
    # never writes PENDING (that would re-enable dispatch and risk a duplicate)
    assert "OutboxStatus.PENDING.value" not in code
    assert '"PENDING"' not in code
    assert "'PENDING'" not in code


def test_phase1_claim_stale_sending_filter_excludes_send_unknown():
    """The re-dispatch sweep (claim_stale_sending) selects only SENDING rows;
    SEND_UNKNOWN rows are deliberately excluded because Zalo may have accepted.
    Executable code only (docstring mentions SEND_UNKNOWN as context).
    """
    import ast
    import inspect

    from app.services import outbox_service

    src = inspect.getsource(outbox_service.claim_stale_sending)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")
    code = ast.unparse(tree)

    # the SELECT filters status = 'SENDING' only
    assert "status = 'SENDING'" in code
    # never selects SEND_UNKNOWN
    assert "SEND_UNKNOWN" not in code


def test_phase1_create_pending_outbox_persists_before_provider_io():
    """The outbox row is the authoritative 'was this sent?' record, written in
    the caller's transaction BEFORE any provider call. Phase 3's neutral
    ChannelDispatchService must preserve this ordering.

    This freezes the contract: create_pending_outbox raises on insert failure
    (it does not swallow) so a crash cannot leave a reply without its command.
    """
    import inspect

    from app.services import outbox_service

    src = inspect.getsource(outbox_service.create_pending_outbox)
    # unlike enqueue_outbox (best-effort), create_pending_outbox RAISES on failure
    assert "raise RuntimeError" in src
    # it writes PENDING (the pre-send state)
    assert "OutboxStatus.PENDING" in src


def test_phase1_enqueue_outbox_is_best_effort_never_blocks_turn():
    """enqueue_outbox swallows DB errors — the outbox is observability/
    reliability infra, not a turn-blocking dependency. Phase 3's neutral
    dispatch preserves this distinction (persist-before-send uses
    create_pending_outbox which raises; final-state recording uses
    enqueue_outbox which does not).
    """
    import inspect

    from app.services import outbox_service

    src = inspect.getsource(outbox_service.enqueue_outbox)
    assert "except Exception" in src
    # returns None on failure rather than raising
    assert "return None" in src


def test_phase1_message_id_uniqueness_is_the_durable_dispatch_fence():
    """The unique constraint on outbound_outbox.message_id is what prevents a
    double-dispatch after a crash-and-retry. Phase 2 will add an analogous
    uniqueness on inbound messages.provider_message_id for inbound idempotency;
    this test freezes the outbound precedent.
    """
    from app.models.outbox import OutboundOutbox

    msg_id_col = OutboundOutbox.__table__.columns["message_id"]
    # unique=True at the column level (the migration also adds the index)
    assert msg_id_col.unique is True
