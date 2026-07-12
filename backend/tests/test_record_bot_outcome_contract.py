"""Signature guard for ConversationService.record_bot_outcome.

``run_turn`` (graph/runner) and the chatbot worker's degradation path call
``record_bot_outcome`` with a fixed keyword set, at turn *finalization* — after
the reply has been computed and sent. If a caller and the service method drift
apart, the call raises ``TypeError`` from inside the turn. That unhandled error
leaves the SQLAlchemy session needing rollback, so later turns on the same
worker cascade into ``PendingRollbackError`` until the worker is restarted —
the bot effectively stops responding.

The graph-runner unit tests stub this method with ``**kwargs`` (deliberately
loose for control-flow isolation), so they cannot detect the drift. These
tests pin the *real* public signature so any caller/service mismatch fails CI
before it can reach production. They are signature-only on purpose: the defect
is a contract violation, and signature introspection is the direct assertion.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.models.conversation import DeliveryStatus
from app.services.conversation import ConversationService
from app.services.conversation.state import ConversationState

# Every keyword the call sites pass (see app/graph/runner.py and
# app/workers/chatbot_worker.py). Keep in sync with the callers.
REQUIRED_KWARGS = {
    "version_at_start",
    "reply",
    "started_at",
    "sent",
    "pending_message_id",
    "external_error",
    "zalo_message_id",
    "stage_timings",
    "lock_owner",
    "delivery_status",
    "trace_id",
    "outcome_metadata",
}


def _keyword_params(fn) -> set[str]:
    return {
        name
        for name, param in inspect.signature(fn).parameters.items()
        if name not in ("self", "conv")
        and param.kind
        in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    }


def test_public_record_bot_outcome_accepts_every_caller_kwarg():
    # This is the method every caller actually binds. If it drops a kwarg a
    # caller passes, the turn crashes at finalization and poisons the session.
    missing = REQUIRED_KWARGS - _keyword_params(ConversationService.record_bot_outcome)
    assert not missing, (
        f"ConversationService.record_bot_outcome no longer accepts {sorted(missing)} "
        f"that the turn callers pass — this drift crashes turns at finalization."
    )


def test_state_impl_record_bot_outcome_accepts_every_caller_kwarg():
    # The public wrapper delegates to ConversationState.record_bot_outcome; the
    # implementation must accept the same kwargs or the delegation itself crashes.
    missing = REQUIRED_KWARGS - _keyword_params(ConversationState.record_bot_outcome)
    assert not missing, (
        f"ConversationState.record_bot_outcome no longer accepts {sorted(missing)} "
        f"that the turn callers pass — this drift crashes turns at finalization."
    )


async def test_public_record_bot_outcome_forwards_extended_outcome_fields():
    service = ConversationService(MagicMock())
    service.state.record_bot_outcome = AsyncMock(return_value=MagicMock())
    conversation = MagicMock()
    started_at = datetime.now(timezone.utc)
    outcome_metadata = {"faq_id": "faq-1"}

    await service.record_bot_outcome(
        conversation,
        version_at_start=3,
        reply="Chào bạn",
        started_at=started_at,
        sent=False,
        delivery_status=DeliveryStatus.SEND_UNKNOWN,
        trace_id="trace-123",
        outcome_metadata=outcome_metadata,
    )

    service.state.record_bot_outcome.assert_awaited_once_with(
        conversation,
        version_at_start=3,
        reply="Chào bạn",
        started_at=started_at,
        sent=False,
        pending_message_id=None,
        external_error=None,
        zalo_message_id=None,
        stage_timings=None,
        lock_owner=None,
        delivery_status=DeliveryStatus.SEND_UNKNOWN,
        trace_id="trace-123",
        outcome_metadata=outcome_metadata,
    )
