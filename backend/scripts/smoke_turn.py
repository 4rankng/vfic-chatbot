#!/usr/bin/env python3
"""Pre-flip blue-green deploy smoke gate.

Runs ONE real bot turn end-to-end against the live service layer (real
``ConversationService`` -> ``ConversationState``) with the LLM agent and the
Zalo transport stubbed, so the turn makes no external calls and costs nothing,
yet still exercises the exact regression surface behind the 2026-07 production
outages:

  * ``claim_send`` / ``create_pending_outbox`` INSERT  -> naive-datetime crash
    (the ``DateTime`` vs ``timestamptz`` model/migration drift)
  * ``record_bot_outcome``                            -> runner<->facade kwarg
    drift (``TypeError: unexpected kwarg``)
  * ``ConversationEventBus.schedule_realtime``        -> ``MissingGreenlet`` in
    the fire-and-forget realtime task

Why the stubs are safe: the smoke dependencies wire the REAL
``ConversationService(db)`` and ``RetrievalRepository(db)``. The former delegates
to ``ConversationState`` -- where all three failure modes live. Only the pure
LLM/transport seams are stubbed, so persistence + realtime run unmodified without
constructing provider clients or resolving integration secrets.

Exit code is 0 ONLY when the turn completes with no raised exception, no
unhandled background-task error, and the session is not left in a needs-rollback
state. Any other outcome must abort the blue-green flip (the old color keeps
serving traffic).

Usage (inside the new-color container, before ``flip_caddy.sh``):

    python -m scripts.smoke_turn

Self-test -- proves the gate actually fails on a broken image (a
``record_bot_outcome`` that raises, mirroring the kwarg-drift outage class):

    python -m scripts.smoke_turn --inject-failure     # MUST exit 1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.conversation_messaging.domain.statuses import DeliveryStatus, MessageSender
from app.core.config import get_settings
from app.graph.safety import DeterministicReplyPolicy
from app.graph.runner import BotRunState, run_turn
from app.graph.types import GraphDeps
from app.models.contact import Contact, ContactChannelIdentity
from app.models.conversation import Conversation, ConversationMode, Message
from app.models.outbox import OutboxStatus, OutboundOutbox

# A non-empty reply that passes the deterministic keyword safety filter and is
# not a banned phrase, so the turn reaches the real send/outcome path.
SMOKE_REPLY = "Kiem tra trien khai thanh cong."  # diacritics-stripped upstream anyway

# Distinctive marker so the throwaway rows are unambiguous and easy to clean up.
SMOKE_MARKER = "__smoke__"


@dataclass
class _SmokeSendResult:
    """Stand-in for the Zalo transport result (the real SendResult/DispatchResult).

    The runner only reads ``ok``/``error_class``/``suppressed`` and hands the
    object to ``_stamp_outbound_telemetry`` (which reads ``msg_id``/``telemetry``).
    """

    ok: bool = True
    error: str | None = None
    error_class: str | None = None
    suppressed: bool = False
    msg_id: str = "smoke"
    telemetry: object = None


class _StubAgent:
    """Canned-reply ``AgentModel`` (Protocol, app/graph/llm.py). No LLM call."""

    async def agent(self, _user_text: str, **_kwargs: object) -> str:
        return SMOKE_REPLY

    async def direct(self, _user_text: str, **_kwargs: object) -> str:
        return SMOKE_REPLY


class _StubZalo:
    """No-op Zalo seam. The status heartbeat (``send_chat_action``) hits this."""

    async def send_message(self, _chat_id: str, _text: str, **_kwargs: object) -> _SmokeSendResult:
        return _SmokeSendResult()

    async def send_chat_action(self, _chat_id: str, _action: str) -> None:
        return None

    def for_conversation(self, _conv: object) -> _StubZalo:
        return self


async def _stub_embedder(_text: str) -> list[float]:
    # Never actually called (the stub agent ignores it and FAQ bypass is
    # hard-disabled), but keeps the turn free of any Gemini dependency.
    return [0.0] * 3072


def _build_smoke_deps(db) -> GraphDeps:
    """Wire the real turn services without constructing unused provider clients."""
    from app.services.conversation import ConversationService
    from app.services.retrieval import RetrievalRepository
    from app.composition.recruitment import build_lead_context

    return GraphDeps(
        db=db,
        agent=_StubAgent(),
        embedder=_stub_embedder,
        zalo=_StubZalo(),
        conversation=ConversationService(db),
        retrieval=RetrievalRepository(db),
        reply_policy=DeterministicReplyPolicy(),
        lead=build_lead_context(db),
    )


async def _seed_smoke_conversation(
    db,
) -> tuple[Conversation, ContactChannelIdentity, Contact, uuid.UUID]:
    """Inline port of tests/integration/_conv_factory.make_conversation.

    The production image does not ship ``tests/``, so the canonical Contact +
    ContactChannelIdentity + Conversation triple (required since Alembic 0047)
    is constructed here against a throwaway, clearly-marked identity. The
    conversation is pre-locked (``bot_lock_owner``/``bot_locked_until`` set,
    ``mode=BOT``) exactly as the webhook does before enqueue, so the turn takes
    the full SENT path and exercises ``claim_send``'s outbox INSERT.
    """
    owner = uuid.uuid4()
    now = datetime.now(timezone.utc)
    contact = Contact()
    db.add(contact)
    await db.flush()
    identity = ContactChannelIdentity(
        contact_id=contact.id,
        provider="zalo_bot",
        account_key="smoke",
        external_id=f"smoke-{uuid.uuid4().hex[:8]}",
    )
    db.add(identity)
    await db.flush()
    conv = Conversation(
        zalo_chat_id=f"{SMOKE_MARKER}{uuid.uuid4().hex[:8]}",
        zalo_channel="bot",
        contact_id=identity.contact_id,
        channel_identity_id=identity.id,
        mode=ConversationMode.BOT,
        bot_lock_owner=owner,
        bot_locked_until=now + timedelta(seconds=300),
        bot_lock_heartbeat_at=now,
    )
    db.add(conv)
    await db.flush()
    # Refresh so server defaults (notably ``version``) materialize before we read
    # them for the optimistic-lock token.
    await db.refresh(conv)
    return conv, identity, contact, owner


async def _cleanup(db, *, conv_id, identity_id, contact_id) -> None:
    """Delete the throwaway rows so the smoke leaves no prod artifact.

    The service layer commits internally (``record_bot_pending`` etc.), so a
    plain rollback is not enough. Outbox rows reference messages directly, so
    they are removed first; deleting the conversation then CASCADEs to
    ``bot_runs`` + ``messages`` (FKs are ``ondelete=CASCADE``).
    """
    msg_ids = (await db.scalars(select(Message.id).where(Message.conversation_id == conv_id))).all()
    if msg_ids:
        await db.execute(delete(OutboundOutbox).where(OutboundOutbox.message_id.in_(msg_ids)))
    await db.execute(delete(Conversation).where(Conversation.id == conv_id))
    await db.execute(delete(ContactChannelIdentity).where(ContactChannelIdentity.id == identity_id))
    await db.execute(delete(Contact).where(Contact.id == contact_id))
    await db.commit()


def _resolved_provider_message_id(
    *,
    canonical_id: str | None,
    compatibility_id: str | None,
    label: str,
) -> str:
    """Resolve the durable provider id while enforcing canonical/alias consistency."""
    if canonical_id and compatibility_id and canonical_id != compatibility_id:
        raise AssertionError(
            f"{label} provider_message_id {canonical_id!r} did not match "
            f"zalo_message_id {compatibility_id!r}"
        )
    provider_id = canonical_id or compatibility_id
    if not provider_id:
        raise AssertionError(f"{label} missing provider message id")
    return provider_id


async def _assert_persisted_delivery_invariant(
    db,
    *,
    conv_id,
    message_id: int | None,
    expected_reply: str = SMOKE_REPLY,
) -> None:
    """Require the exact BOT message/outbox terminal state the smoke gate exists to prove."""
    if message_id is None:
        raise AssertionError("run_turn did not persist a pending_message_id for the smoke turn")

    bot_messages = (
        await db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.sender == MessageSender.BOT,
            )
            .order_by(Message.id.asc())
        )
    ).all()
    if len(bot_messages) != 1:
        raise AssertionError(
            f"expected exactly one BOT message for the smoke conversation, found {len(bot_messages)}"
        )

    msg = bot_messages[0]
    if msg.id != message_id:
        raise AssertionError(
            f"smoke BOT message id {msg.id} did not match pending_message_id {message_id}"
        )
    if msg.body != expected_reply:
        raise AssertionError("smoke BOT message body did not persist the expected reply")
    if msg.delivery_status != DeliveryStatus.SENT:
        raise AssertionError(
            f"smoke BOT message delivery_status was {msg.delivery_status!s}, expected SENT"
        )
    message_provider_id = _resolved_provider_message_id(
        canonical_id=msg.provider_message_id,
        compatibility_id=msg.zalo_message_id,
        label="smoke BOT message",
    )
    if msg.external_error is not None:
        raise AssertionError("smoke BOT message should not retain external_error after SENT")

    outboxes = (
        await db.scalars(
            select(OutboundOutbox)
            .where(OutboundOutbox.message_id.in_([row.id for row in bot_messages]))
            .order_by(OutboundOutbox.id.asc())
        )
    ).all()
    if len(outboxes) != 1:
        raise AssertionError(
            f"expected exactly one outbound_outbox row for the smoke BOT message, found {len(outboxes)}"
        )

    outbox = outboxes[0]
    if outbox.message_id != message_id:
        raise AssertionError(
            f"smoke outbound_outbox message_id {outbox.message_id} did not match pending_message_id {message_id}"
        )
    if outbox.status != OutboxStatus.SENT.value:
        raise AssertionError(
            f"smoke outbound_outbox status was {outbox.status!r}, expected {OutboxStatus.SENT.value!r}"
        )
    outbox_provider_id = _resolved_provider_message_id(
        canonical_id=outbox.provider_message_id,
        compatibility_id=outbox.zalo_message_id,
        label="smoke outbound_outbox",
    )
    if outbox_provider_id != message_provider_id:
        raise AssertionError(
            "smoke outbound_outbox provider message id did not match the BOT message"
        )


async def _run_smoke(*, inject_failure: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Capture exceptions escaping fire-and-forget tasks (the MissingGreenlet
    # surface). asyncio only invokes this for tasks whose exceptions were never
    # retrieved, which is exactly the failure mode that silently broke prod.
    loop = asyncio.get_running_loop()
    task_errors: list[BaseException] = []

    def _on_task_exception(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, BaseException):
            task_errors.append(exc)

    loop.set_exception_handler(_on_task_exception)

    # Stub the Zalo transport seam so the smoke makes NO real Zalo HTTP call.
    # The runner reaches Zalo via ConversationService.dispatch_outbound_message
    # -> dispatch_message_outbox (not deps.zalo), so this is the right seam.
    import app.services.outbox_service as outbox_service

    real_dispatch_message_outbox = outbox_service.dispatch_message_outbox

    async def _stub_dispatch_message_outbox(_db, *, message_id: int) -> _SmokeSendResult:  # noqa: ARG001
        # ConversationService.dispatch_outbound_message calls this as
        # ``dispatch_message_outbox(self.db, message_id=...)`` (db positional),
        # matching the real signature ``dispatch_message_outbox(db, *, message_id)``.
        return _SmokeSendResult(msg_id=f"smoke-{message_id}")

    outbox_service.dispatch_message_outbox = _stub_dispatch_message_outbox  # type: ignore[assignment]

    if inject_failure:
        # Simulate the kwarg-drift outage class: a record_bot_outcome that raises.
        from app.services.conversation import ConversationService

        async def _boom(self, _conv, **_kwargs):  # noqa: ANN001, ARG001
            raise TypeError("injected record_bot_outcome kwarg drift")

        ConversationService.record_bot_outcome = _boom  # type: ignore[assignment,method-assign]

    conv_id = identity_id = contact_id = None
    result_code = 1
    success_message = None
    cleanup_failed = False
    try:
        # Seed in its own session, then CLOSE it. The turn runs in a FRESH
        # session so run_turn's ``svc.get`` loads the conversation the same way
        # the RQ worker does -- via a select() that fires the ``selectin``
        # relationships (contact, contact.channel_identities). Seeding + running
        # in one session pollutes the identity map and returns a bare object,
        # which then MissingGreenlets when ``ConversationOut`` walks the graph.
        async with session_factory() as seed_db:
            conv, identity, contact, owner = await _seed_smoke_conversation(seed_db)
            await seed_db.commit()
            conv_id, identity_id, contact_id = conv.id, identity.id, contact.id
            version_at_start = int(conv.version or 0)

        async with session_factory() as db:
            deps = _build_smoke_deps(db)

            state = BotRunState(
                conversation_id=str(conv_id),
                version_at_start=version_at_start,
                user_text="smoke probe",
                lock_owner=str(owner),
            )
            outcome = await run_turn(state, deps)

            # Let fire-and-forget realtime tasks surface before we inspect.
            await asyncio.sleep(0.5)

            # A poisoned session (PendingRollbackError cascade) would raise here.
            await db.execute(select(1))

            if task_errors:
                _fail(f"background task error(s): {[type(e).__name__ for e in task_errors]}")
            else:
                result = outcome.get("outcome") if isinstance(outcome, dict) else None
                if result != "sent":
                    _fail(f"unexpected outcome: {result!r}")
                else:
                    await _assert_persisted_delivery_invariant(
                        db,
                        conv_id=conv_id,
                        message_id=state.pending_message_id,
                        expected_reply=SMOKE_REPLY,
                    )
                    success_message = f"SMOKE OK: outcome={result!r}"
                    result_code = 0
    except Exception as exc:  # noqa: BLE001 -- the whole point is to catch anything
        import traceback

        _fail(f"turn raised {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    finally:
        outbox_service.dispatch_message_outbox = real_dispatch_message_outbox  # type: ignore[assignment]
        # Best-effort cleanup of the throwaway rows (skipped only if seeding
        # itself failed before a conversation existed).
        if conv_id is not None:
            try:
                async with session_factory() as cleanup_db:
                    await _cleanup(
                        cleanup_db,
                        conv_id=conv_id,
                        identity_id=identity_id,
                        contact_id=contact_id,
                    )
            except Exception as cleanup_exc:  # noqa: BLE001 -- cleanup must fail closed
                cleanup_failed = True
                _fail(f"cleanup incomplete: {cleanup_exc}")
        await engine.dispose()

    if cleanup_failed:
        return 1
    if success_message is not None:
        print(success_message, file=sys.stderr)
    return result_code


def _fail(message: str) -> None:
    print(f"SMOKE FAIL: {message}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inject-failure",
        action="store_true",
        help="self-test: make record_bot_outcome raise; the gate MUST exit 1",
    )
    args = parser.parse_args()
    return asyncio.run(_run_smoke(inject_failure=args.inject_failure))


if __name__ == "__main__":
    raise SystemExit(main())
