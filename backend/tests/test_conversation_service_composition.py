"""``ConversationService`` composes named parts; callers reach the part they mean.

ARCH-24 shrank the facade from the union of every repository/state method to the
narrow graph-port surface plus the cross-part orchestrations. The risk that
shrink introduces is not a crash (the imports fail loudly) but a *silent*
misrouting: a lifecycle transition that reaches the reads, a viewer-scoped inbox
read that bypasses the scope, or a forwarder that creeps back in and lets the two
surfaces drift apart again. These tests pin the composition and the routing that
the API and the webhook depend on.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation import ConversationService
from app.services.conversation.events import ConversationEventBus
from app.services.conversation.repository import ConversationRepository
from app.services.conversation.state import ConversationState


def test_the_composed_parts_are_the_ones_that_own_the_work():
    """One service, three parts, each constructed over the SAME session.

    A facade that built its parts over a different session (or left one of them
    out) would still import and still answer calls, so the identity of the parts
    is what makes the composition checkable.
    """
    db = AsyncMock()
    svc = ConversationService(db)

    assert svc.db is db
    assert isinstance(svc.repo, ConversationRepository)
    assert isinstance(svc.events, ConversationEventBus)
    assert isinstance(svc.state, ConversationState)
    # State reads through the very repository the facade exposes, and publishes
    # on the very bus — so a mutation's own read cannot see a different snapshot.
    assert svc.state.repo is svc.repo
    assert svc.state.events is svc.events


def test_the_reconcile_sweep_reaches_the_repository_through_the_mixin():
    """The sweep's two entry points stay methods on ``ConversationRepository``.

    They were moved to ``reconcile_queries.py`` as a mixin; the tick calls them
    as repository methods. If the mixin were dropped from the bases, every
    reconcile tick would fail on the first candidate.
    """
    from app.services.conversation.reconcile_queries import ReconcileQueriesMixin

    assert issubclass(ConversationRepository, ReconcileQueriesMixin)
    assert callable(ConversationRepository.find_reconcile_candidates)
    assert callable(ConversationRepository.latest_inbound_never_given_a_turn)


def test_recruiter_replies_and_receipts_are_reachable_through_the_state():
    """The split-out messaging/receipt half is still on the recruiter state.

    ``recruiter_receipts.py`` holds the replies and the Zalo receipts as a
    mixin; ``ConversationState`` (the composed public type every caller builds)
    must still expose them, or the recruiter reply endpoints and the OA receipt
    handler would raise ``AttributeError`` on first use.
    """
    from app.services.conversation.recruiter_receipts import RecruiterReceiptsMixin
    from app.services.conversation.recruiter_path import RecruiterMessagingState

    assert issubclass(RecruiterMessagingState, RecruiterReceiptsMixin)
    for name in (
        "record_recruiter_message",
        "prepare_recruiter_message",
        "finalize_recruiter_delivery",
        "retry_recruiter_message",
        "apply_delivery_receipt",
        "apply_delivery_receipt_batch",
    ):
        assert callable(getattr(ConversationState, name)), name
        assert callable(getattr(RecruiterMessagingState, name)), name


@pytest.mark.asyncio
async def test_claim_send_still_delegates_to_the_state_seam():
    """``claim_send`` is a verified-atomic seam: its delegation target is fixed.

    The TOCTOU claim is the one forwarder the architecture notes single out as
    load-bearing, so a refactor that re-pointed it at the repository (or inlined
    it) would be a behaviour change dressed as a cleanup.
    """
    svc = ConversationService(AsyncMock())
    svc.state.claim_send = AsyncMock(return_value=True)
    svc.repo.claim_send = AsyncMock(return_value=False)  # type: ignore[attr-defined]

    claimed = await svc.claim_send(
        MagicMock(),
        version_at_start=3,
        lock_owner=uuid.uuid4(),
        pending_message_id=None,
        reply="xin chào",
    )

    assert claimed is True
    svc.state.claim_send.assert_awaited_once()
    svc.repo.claim_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_release_and_enqueue_releases_through_state_then_enqueues_the_result():
    """The release orchestration: state transition first, enqueue on the RELEASED row.

    Two orderings break differently and both are silent. Enqueueing before the
    release would queue a turn stamped with the pre-release version, so the
    worker's ownership recheck would fail and the pending inbound would never be
    answered; releasing after the enqueue would race the recruiter's own
    release. The enqueued job must therefore carry the version the RELEASE
    produced, not the one the endpoint loaded.
    """
    conv = SimpleNamespace(id=uuid.uuid4(), version=5)
    released = SimpleNamespace(id=conv.id, version=6)
    events: list[str] = []

    pending = SimpleNamespace(
        body="Tin nhắn chưa trả lời",
        zalo_message_id="zalo-msg-1",
        created_at=datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc),
    )
    lock_owner = uuid.UUID("00000000-0000-0000-0000-0000000000bb")

    svc = ConversationService(AsyncMock())
    svc.state.release = AsyncMock(side_effect=lambda c, a: events.append("release") or released)
    svc.repo.latest_unanswered_worker_message = AsyncMock(return_value=pending)
    svc.acquire_lock = AsyncMock(return_value=lock_owner)

    def enqueue(job: dict) -> bool:
        events.append("enqueue")
        enqueued.append(job)
        return True

    enqueued: list[dict] = []
    result = await svc.release_and_enqueue_unanswered(conv, SimpleNamespace(), enqueue=enqueue)

    assert result is released
    assert events == ["release", "enqueue"]
    # The job the worker receives is stamped with the RELEASED version — the
    # optimistic-lock token the turn re-checks against.
    assert enqueued[0]["version_at_start"] == released.version
    assert enqueued[0]["version_at_start"] != conv.version
    assert enqueued[0]["user_text"] == pending.body
    assert enqueued[0]["lock_owner"] == str(lock_owner)


@pytest.mark.asyncio
async def test_webhook_ack_guards_run_through_state_and_the_inbound_read_through_repo():
    """The ack path names the part that owns each step.

    The takeover race guard only works because ``run_start_guard``/``acquire_lock``
    read the column-scoped reload on the state machine, and the explicit-name
    lookup is a repository read. Routing either through the wrong part would leave
    the code importing fine while reading a different snapshot.
    """
    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        version=3,
        mode="BOT",
    )
    order: list[str] = []
    svc = MagicMock()

    async def _ensure(*_a, **_k):
        order.append("ensure")
        return conv

    async def _record_inbound(*_a, **_k):
        order.append("record_inbound")

    def _guard(_c):
        order.append("run_start_guard")
        return True

    async def _acquire_lock(_conv_id):
        order.append("acquire_lock")
        return uuid.uuid4()

    svc.state.ensure = AsyncMock(side_effect=_ensure)
    svc.state.record_inbound = AsyncMock(side_effect=_record_inbound)
    svc.state.run_start_guard = MagicMock(side_effect=_guard)
    svc.state.acquire_lock = AsyncMock(side_effect=_acquire_lock)
    svc.repo.last_messages = AsyncMock(return_value=[])
    db = MagicMock()
    db.refresh = AsyncMock()

    with (
        patch("app.services.webhook.ConversationService", lambda _db: svc),
        patch(
            "app.services.webhook.MessageDedupService.claim",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_name",
            AsyncMock(return_value=None),
        ),
    ):
        result = await ZaloWebhookService.handle(
            db,
            {"message": {"message_id": "m1", "chat": {"id": "bot-user-1"}, "text": "Chào"}},
            enqueue=lambda _job: True,
        )

    assert result == {"status": "processing", "conversation_id": str(conv.id)}
    assert order == ["ensure", "record_inbound", "run_start_guard", "acquire_lock"]
