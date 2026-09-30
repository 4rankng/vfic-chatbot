#!/usr/bin/env python3
"""Pre-flip blue-green deploy smoke gate.

Runs real bot turns end-to-end against the live service layer (real
``ConversationService`` -> ``ConversationState``) with the LLM agent and the
Zalo transport stubbed, so a turn makes no external calls and costs nothing,
yet still exercises the exact regression surface behind the 2026-07 production
outages:

  * ``claim_send`` / ``create_pending_outbox`` INSERT  -> naive-datetime crash
    (the ``DateTime`` vs ``timestamptz`` model/migration drift)
  * ``record_bot_outcome``                            -> runner<->facade kwarg
    drift (``TypeError: unexpected kwarg``)
  * ``ConversationEventBus.schedule_realtime``        -> ``MissingGreenlet`` in
    the fire-and-forget realtime task

Each probe seeds its own throwaway conversation and runs one turn. The gate
passes only when EVERY probe records its exact terminal state, so the flip is
gated on the same delivery machinery a candidate receives:

  * ``single-message``  -- progressive send OFF: the pre-existing path.
  * ``progressive-send`` -- progressive send ON with a streaming stub agent:
    the early bubble AND the remainder must both persist as SENT, each with its
    own finalized outbox command, and together they must carry the streamed
    answer exactly once.
  * ``progressive-send-failure`` -- progressive send ON, the lane dies right
    after the early bubble reached the wire. A bubble the candidate is already
    reading must never be blanked: the row stays SENT with its own text and its
    outbox command is terminalized (REL-13), never overwritten with the
    "nothing was sent" empty reply the failure paths used to record.
  * ``support-oa-hotline`` -- a thread on the TingTing support OA (which serves
    the reset flow only). A confident non-support question gets the fixed
    hotline reply, DELIVERED, and nothing is queued behind it: the thread stays
    BOT, no needs_human, no escalation note (operator rule 2026-09-29 — no
    human works this OA). The reply must still be delivered because the fixed
    escalation copy is the employee's only route to help.

Why the stubs are safe: the smoke dependencies wire the REAL
``ConversationService(db)`` and ``RetrievalRepository(db)``. The former delegates
to ``ConversationState`` -- where all the failure modes above live. Only the pure
LLM/transport seams are stubbed, so persistence + realtime run unmodified without
constructing provider clients or resolving integration secrets. The progressive
probes add no wall-clock waiting: the stream is a canned answer and the one
cross-task rendezvous (the failing lane waits for the transport stub's ack) is a
bounded guard, so a path that never sends fails the gate instead of hanging it.

Exit code is 0 ONLY when every turn completes with no raised exception, no
unhandled background-task error, and the sessions are not left in a
needs-rollback state. Any other outcome must abort the blue-green flip (the old
color keeps serving traffic).

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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.conversation_messaging.domain.statuses import DeliveryStatus, MessageSender
from app.core.config import get_settings
from app.graph.runner import BotRunState, run_turn
from app.graph.types import GraphDeps
from app.models.contact import Contact, ContactChannelIdentity
from app.models.conversation import Conversation, ConversationMode, Message
from app.models.outbox import OutboxStatus, OutboundOutbox

# Any non-empty reply reaches the real send/outcome path.
SMOKE_REPLY = "Kiem tra trien khai thanh cong."  # diacritics-stripped upstream anyway
# Distinctive marker so the throwaway rows are unambiguous and easy to clean up.
SMOKE_MARKER = "__smoke__"

# The progressive probes stream a canned answer instead of returning it whole.
# Shape (all three properties are load-bearing, see the module docstring):
#   * it clears PROGRESSIVE_BUBBLE_MIN_CHARS before the FIRST sentence end, so
#     the sender really splits instead of falling back to the single-message
#     path, and the remainder after that boundary is non-empty;
#   * it stays under PROGRESSIVE_MAX_WAIT_CHARS, past which the sender gives up
#     and the turn degrades to one message;
#   * it carries a concrete answer signal (a digit) so it passes the substance
#     gate, and no phone/email/job-id shape, so grounding ships it unchanged.
SMOKE_STREAM_PARTS = (
    "Day la lan kiem tra trien khai cua he thong danh dau mau moi, so 3 duoc chay thu ",
    "truoc khi chuyen sang mau chinh thuc. ",
    "Buoc dau kiem tra cac bang du lieu va cot trang thai cua phien ban truoc khi ",
    "chay lai toan bo luong trich xuat, lap chi muc va doi chieu ket qua. ",
    "Ket qua cua lan chay nay duoc ghi lai de doi chieu voi lan chay truoc do, ",
    "va bao cao trien khai duoc dong lai ngay sau khi hoan tat. ",
)
SMOKE_STREAM_REPLY = "".join(SMOKE_STREAM_PARTS)

# How long the failing lane waits for the transport stub to report that the
# early bubble really went out. A path that never sends must fail the gate, not
# hang the deploy, so this is a bound on a broken build rather than a sleep.
WIRE_ACK_TIMEOUT_SECONDS = 30.0


@dataclass
class _SmokeSendResult:
    """Stand-in for the Zalo transport result (the real SendResult/DispatchResult).

    The runner only reads ``ok``/``error_class``/``suppressed`` and hands the
    object to ``_stamp_outbound_telemetry`` (which reads ``msg_id``/``telemetry``).
    ``outbox_id`` is the row the real dispatcher claimed and returns: the
    progressive sender terminalizes the early bubble against that id, so a
    stand-in without it would collapse the two-bubble split into a single send.
    """

    ok: bool = True
    error: str | None = None
    error_class: str | None = None
    suppressed: bool = False
    msg_id: str = "smoke"
    telemetry: object = None
    outbox_id: int | None = None


class _StubAgent:
    """Canned-reply ``AgentModel`` (Protocol, app/graph/llm.py). No LLM call."""

    async def agent(self, _user_text: str, **_kwargs: object) -> str:
        return SMOKE_REPLY


class _StubStreamingAgent:
    """Streams the canned answer through ``on_delta`` before returning it.

    Progressive send reads the answer as the provider produces it, so a stub
    that never calls ``on_delta`` would leave the flag on with nothing to send
    and the gate would pass without ever opening a bubble. The parts are pushed
    with a bare ``asyncio.sleep(0)`` yield between them -- not a wall-clock
    wait -- so the early sender runs while the lane is still generating, which
    is the interleaving production sees.
    """

    async def agent(
        self,
        _user_text: str,
        *,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
        **_kwargs: object,
    ) -> str:
        for part in SMOKE_STREAM_PARTS:
            if on_delta is not None:
                await on_delta(part)
            await asyncio.sleep(0)
        return SMOKE_STREAM_REPLY


class _StubFailingStreamingAgent:
    """Streams one sendable bubble, waits for the wire, then fails the lane.

    This is the REL-13 shape: the candidate is already reading the bubble when
    the lane dies, so the terminal path has to record THAT message instead of
    the "nothing was sent" empty reply. The wait is on the transport seam's
    ack, so the failure can only land after the bubble was really dispatched
    rather than racing it.
    """

    def __init__(self, wire_ack: asyncio.Event) -> None:
        self.wire_ack = wire_ack

    async def agent(
        self,
        _user_text: str,
        *,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
        **_kwargs: object,
    ) -> str:
        if on_delta is not None:
            # One delta carrying the whole answer: a complete, sendable bubble
            # is available to the sender however the two tasks interleave.
            await on_delta(SMOKE_STREAM_REPLY)
        await asyncio.wait_for(self.wire_ack.wait(), timeout=WIRE_ACK_TIMEOUT_SECONDS)
        raise RuntimeError("smoke probe: the agent lane failed after the early bubble was sent")


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


def _smoke_graph_deps(db, *, agent, progressive_send: bool) -> GraphDeps:
    """Wire the real turn services without constructing unused provider clients."""
    from app.services.conversation import ConversationService
    from app.services.retrieval import RetrievalRepository
    from app.composition.recruitment import build_lead_context

    return GraphDeps(
        db=db,
        agent=agent,
        embedder=_stub_embedder,
        zalo=_StubZalo(),
        conversation=ConversationService(db),
        retrieval=RetrievalRepository(db),
        lead=build_lead_context(db),
        progressive_send=progressive_send,
    )


def _build_smoke_deps(db) -> GraphDeps:
    """Progressive send OFF: the pre-existing single-message delivery path."""
    return _smoke_graph_deps(db, agent=_StubAgent(), progressive_send=False)


class _SupportOaRetrieval:
    """Real retrieval with the TingTing reset flow pinned to the support OA.

    ``_tingting_reset_allowed`` consults exactly one retrieval read
    (``tingting_reset_oa_id``) and fails closed on a read error, so pinning that
    single answer is what puts the turn on the support-OA handoff branch; every
    other call delegates to the real repository.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner

    async def tingting_reset_oa_id(self) -> str:
        from app.channels.types import TINGTING_OA_ACCOUNT_KEY

        return TINGTING_OA_ACCOUNT_KEY

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class _StubTurnDecisions:
    """Jev stand-in: one fixed intent, no network, no provider client.

    The support-OA probes need a *readable* message on purpose: the OA hands a
    confident non-support question to a human and asks its own question when the
    intent is unclear, and which of the two happens must not depend on whether a
    real Jev call was reachable from the smoke environment.
    """

    def __init__(self, intent: str, *, confidence: float = 0.95) -> None:
        self._intent = intent
        self._confidence = confidence

    async def decide_turn(
        self, *, user_text, recent_messages, profile_name="", include_gender=True
    ):
        from app.graph.ports import TurnDecisions

        return TurnDecisions(intent=self._intent, intent_confidence=self._confidence)


def _build_support_oa_deps(db, *, intent: str) -> GraphDeps:
    """The support OA, with Jev's verdict for the inbound pinned by ``intent``.

    The agent is a stub: it answers the clarifying turn (the bot asks which
    problem) and would answer a non-support question too, which is exactly what
    the handoff probe must never see.
    """
    deps = _smoke_graph_deps(db, agent=_StubAgent(), progressive_send=False)
    return replace(
        deps,
        retrieval=_SupportOaRetrieval(deps.retrieval),
        turn_decisions=_StubTurnDecisions(intent),
    )


def _build_progressive_smoke_deps(db) -> GraphDeps:
    """Progressive send ON with a streaming agent: early bubble plus remainder."""
    return _smoke_graph_deps(db, agent=_StubStreamingAgent(), progressive_send=True)


def _build_failing_progressive_smoke_deps(db) -> GraphDeps:
    """Progressive send ON with a lane that dies once the bubble reached the wire."""
    return _smoke_graph_deps(
        db,
        agent=_StubFailingStreamingAgent(asyncio.Event()),
        progressive_send=True,
    )


def _dispatch_signal(deps: GraphDeps) -> asyncio.Event | None:
    """The stub agent's transport-ack event, when this probe's agent has one.

    The transport stub sets it the moment a command reaches the (stubbed)
    channel, which is how the failing-lane probe guarantees the lane can only
    die AFTER the early bubble is with the candidate. Probes whose agent never
    waits on it have no signal.
    """
    return getattr(getattr(deps, "agent", None), "wire_ack", None)


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


async def _seed_support_oa_conversation(
    db,
) -> tuple[Conversation, ContactChannelIdentity, Contact, uuid.UUID]:
    """Seed a TingTing support-OA thread, pre-locked exactly as the webhook leaves it.

    Same triple as ``_seed_smoke_conversation``, but on the linked support OA:
    the channel identity is ``zalo_oa``/``tingting`` and the alias carries the OA
    (``oa:<account_key>:<user_id>``), which is what ``_tingting_reset_allowed``
    reads to decide this channel serves the reset flow.
    """
    from app.channels.types import TINGTING_OA_ACCOUNT_KEY, oa_chat_id

    owner = uuid.uuid4()
    now = datetime.now(timezone.utc)
    external_id = f"{SMOKE_MARKER}{uuid.uuid4().hex[:8]}"
    contact = Contact()
    db.add(contact)
    await db.flush()
    identity = ContactChannelIdentity(
        contact_id=contact.id,
        provider="zalo_oa",
        account_key=TINGTING_OA_ACCOUNT_KEY,
        external_id=external_id,
    )
    db.add(identity)
    await db.flush()
    conv = Conversation(
        zalo_chat_id=oa_chat_id(TINGTING_OA_ACCOUNT_KEY, external_id),
        zalo_channel="oa",
        contact_id=identity.contact_id,
        channel_identity_id=identity.id,
        mode=ConversationMode.BOT,
        bot_lock_owner=owner,
        bot_locked_until=now + timedelta(seconds=300),
        bot_lock_heartbeat_at=now,
    )
    db.add(conv)
    await db.flush()
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


async def _load_bot_messages(db, *, conv_id) -> list[Message]:
    """Every BOT message of the smoke conversation, oldest first."""
    return (
        await db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.sender == MessageSender.BOT,
            )
            .order_by(Message.id.asc())
        )
    ).all()


async def _assert_delivered_bot_row(
    db,
    *,
    message: Message,
    expected_body: str,
    label: str,
    streamed_edge: str | None = None,
) -> None:
    """Require one delivered BOT row and its single outbox command to be terminal.

    Shared by every probe so "delivered" cannot drift between the single-message
    path and the two progressive paths: the body the candidate was sent, a SENT
    status, a persisted provider id, no retained transport error, and exactly
    one outbox row on the same terminal state.

    ``streamed_edge`` is ``"prefix"``/``"suffix"`` for the halves of the
    progressive split, where a row carries a slice of the streamed answer
    rather than all of it. The slice must still be a non-blank piece of that
    answer at that end, which is what a blanked or replaced bubble fails on.
    """
    if streamed_edge == "prefix":
        aligned = bool(message.body) and expected_body.startswith(message.body)
    elif streamed_edge == "suffix":
        aligned = bool(message.body) and expected_body.endswith(message.body)
    elif message.body != expected_body:
        raise AssertionError("smoke BOT message body did not persist the expected reply")
    else:
        aligned = True
    if not aligned:
        raise AssertionError(
            f"{label} body {message.body!r} was not a non-blank {streamed_edge} "
            "of the streamed reply"
        )
    if message.delivery_status != DeliveryStatus.SENT:
        raise AssertionError(
            f"{label} delivery_status was {message.delivery_status!s}, expected SENT"
        )
    message_provider_id = _resolved_provider_message_id(
        canonical_id=message.provider_message_id,
        compatibility_id=message.zalo_message_id,
        label=label,
    )
    if message.external_error is not None:
        raise AssertionError(f"{label} should not retain external_error after SENT")

    outboxes = (
        await db.scalars(
            select(OutboundOutbox)
            .where(OutboundOutbox.message_id == message.id)
            .order_by(OutboundOutbox.id.asc())
        )
    ).all()
    if len(outboxes) != 1:
        raise AssertionError(
            f"expected exactly one outbound_outbox row for the {label}, found {len(outboxes)}"
        )

    outbox = outboxes[0]
    if outbox.message_id != message.id:
        raise AssertionError(
            f"{label} outbound_outbox message_id {outbox.message_id} did not match the message id"
        )
    if outbox.status != OutboxStatus.SENT.value:
        raise AssertionError(
            f"{label} outbound_outbox status was {outbox.status!r}, expected {OutboxStatus.SENT.value!r}"
        )
    outbox_provider_id = _resolved_provider_message_id(
        canonical_id=outbox.provider_message_id,
        compatibility_id=outbox.zalo_message_id,
        label=f"{label} outbound_outbox",
    )
    if outbox_provider_id != message_provider_id:
        raise AssertionError(
            f"{label} outbound_outbox provider message id did not match the message"
        )


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

    bot_messages = await _load_bot_messages(db, conv_id=conv_id)
    if len(bot_messages) != 1:
        raise AssertionError(
            f"expected exactly one BOT message for the smoke conversation, found {len(bot_messages)}"
        )

    msg = bot_messages[0]
    if msg.id != message_id:
        raise AssertionError(
            f"smoke BOT message id {msg.id} did not match pending_message_id {message_id}"
        )
    await _assert_delivered_bot_row(
        db,
        message=msg,
        expected_body=expected_reply,
        label="smoke BOT message",
    )


async def _assert_progressive_delivery_invariant(
    db,
    *,
    conv_id,
    remainder_message_id: int | None,
    expected_reply: str = SMOKE_STREAM_REPLY,
) -> None:
    """Require BOTH progressive rows to survive the turn: the bubble and the rest.

    The early bubble is already with the candidate when the remainder is sent, so
    each half owns its own message row and its own outbox command. Two terminal
    rows that concatenate back to the streamed answer also prove the split sent
    no text twice and dropped none of it.
    """
    if remainder_message_id is None:
        raise AssertionError("run_turn did not persist a pending_message_id for the smoke turn")

    bot_messages = await _load_bot_messages(db, conv_id=conv_id)
    if len(bot_messages) != 2:
        raise AssertionError(
            "expected exactly two BOT messages for the smoke conversation (the early "
            f"bubble and its remainder), found {len(bot_messages)}"
        )

    bubble, remainder = bot_messages
    if remainder.id != remainder_message_id:
        raise AssertionError(
            f"progressive remainder message id {remainder.id} did not match "
            f"pending_message_id {remainder_message_id}"
        )
    await _assert_delivered_bot_row(
        db,
        message=bubble,
        expected_body=expected_reply,
        label="progressive early bubble",
        streamed_edge="prefix",
    )
    await _assert_delivered_bot_row(
        db,
        message=remainder,
        expected_body=expected_reply,
        label="progressive remainder",
        streamed_edge="suffix",
    )
    if bubble.body + remainder.body != expected_reply:
        raise AssertionError(
            "the progressive bubbles did not carry the streamed answer exactly once "
            f"({len(bubble.body)} + {len(remainder.body)} chars, expected {len(expected_reply)})"
        )


async def _assert_delivered_bubble_invariant(
    db,
    *,
    conv_id,
    message_id: int | None,
    expected_reply: str = SMOKE_STREAM_REPLY,
) -> None:
    """Require a bubble that already reached the wire to survive a failed lane.

    The failure-after-bubble turn records the bubble as this turn's answer, so
    the row stays SENT with the text the candidate is reading and its outbox
    command is terminalized. The regression this exists for is the opposite: the
    failure path recording "nothing was sent" against the bubble's own row, which
    blanked a delivered message and left its command stuck in SENDING.
    """
    if message_id is None:
        raise AssertionError("run_turn did not persist a pending_message_id for the smoke turn")

    bot_messages = await _load_bot_messages(db, conv_id=conv_id)
    if len(bot_messages) != 1:
        raise AssertionError(
            "expected exactly one BOT message for the failed progressive turn, found "
            f"{len(bot_messages)}"
        )

    bubble = bot_messages[0]
    if bubble.id != message_id:
        raise AssertionError(
            f"delivered bubble message id {bubble.id} did not match pending_message_id {message_id}"
        )
    await _assert_delivered_bot_row(
        db,
        message=bubble,
        expected_body=expected_reply,
        label="delivered early bubble",
        streamed_edge="prefix",
    )


async def _run_probe(probe: "_SmokeProbe", *, inject_failure: bool) -> int:
    """Run one bot turn end to end and require its persisted terminal state."""
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

    conv_id = identity_id = contact_id = None
    result_code = 1
    success_message = None
    cleanup_failed = False
    shipped_record_bot_outcome = None
    try:
        # Seed in its own session, then CLOSE it. The turn runs in a FRESH
        # session so run_turn's ``svc.get`` loads the conversation the same way
        # the RQ worker does -- via a select() that fires the ``selectin``
        # relationships (contact, contact.channel_identities). Seeding + running
        # in one session pollutes the identity map and returns a bare object,
        # which then MissingGreenlets when ``ConversationOut`` walks the graph.
        async with session_factory() as seed_db:
            conv, identity, contact, owner = await probe.seed(seed_db)
            await seed_db.commit()
            conv_id, identity_id, contact_id = conv.id, identity.id, contact.id
            version_at_start = int(conv.version or 0)

        async with session_factory() as db:
            deps = probe.build_deps(db)
            wire_ack = _dispatch_signal(deps)

            async def _stub_dispatch_message_outbox(
                dispatch_db, *, message_id: int
            ) -> _SmokeSendResult:
                # ConversationService.dispatch_outbound_message calls this as
                # ``dispatch_message_outbox(self.db, message_id=...)`` (db positional),
                # matching the real signature
                # ``dispatch_message_outbox(db, *, message_id)``.
                #
                # The real dispatcher returns the row it claimed, and the
                # progressive sender terminalizes the early bubble against that
                # id, so the stand-in reports the row claim_send just wrote.
                outbox_id = await dispatch_db.scalar(
                    select(OutboundOutbox.id).where(OutboundOutbox.message_id == message_id)
                )
                if wire_ack is not None:
                    wire_ack.set()
                return _SmokeSendResult(
                    msg_id=f"smoke-{message_id}",
                    outbox_id=None if outbox_id is None else int(outbox_id),
                )

            outbox_service.dispatch_message_outbox = _stub_dispatch_message_outbox  # type: ignore[assignment]

            if inject_failure:
                # Simulate the kwarg-drift outage class: a record_bot_outcome that raises.
                from app.services.conversation import ConversationService

                shipped_record_bot_outcome = ConversationService.record_bot_outcome

                async def _boom(self, conv, **_kwargs):  # noqa: ANN001, ARG001
                    raise TypeError("injected record_bot_outcome kwarg drift")

                ConversationService.record_bot_outcome = _boom  # type: ignore[assignment,method-assign]

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
                if result != probe.expected_outcome:
                    _fail(f"unexpected outcome: {result!r}, expected {probe.expected_outcome!r}")
                else:
                    await probe.check(db, conv_id=conv_id, state=state)
                    success_message = f"SMOKE OK [{probe.label}]: outcome={result!r}"
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
        if shipped_record_bot_outcome is not None:
            # The next probe runs against the class the image shipped, so undo
            # the injected method instead of leaking it into every later turn.
            ConversationService.record_bot_outcome = shipped_record_bot_outcome  # type: ignore[method-assign]
        await engine.dispose()

    if cleanup_failed:
        return 1
    if success_message is not None:
        print(success_message, file=sys.stderr)
    return result_code


async def _check_single_message(db, *, conv_id, state) -> None:
    await _assert_persisted_delivery_invariant(
        db,
        conv_id=conv_id,
        message_id=state.pending_message_id,
        expected_reply=SMOKE_REPLY,
    )


async def _check_progressive_pair(db, *, conv_id, state) -> None:
    await _assert_progressive_delivery_invariant(
        db,
        conv_id=conv_id,
        remainder_message_id=state.pending_message_id,
        expected_reply=SMOKE_STREAM_REPLY,
    )


async def _check_delivered_bubble(db, *, conv_id, state) -> None:
    await _assert_delivered_bubble_invariant(
        db,
        conv_id=conv_id,
        message_id=state.pending_message_id,
        expected_reply=SMOKE_STREAM_REPLY,
    )


async def _check_support_oa_hotline(db, *, conv_id, state) -> None:
    """The hotline reply reached the employee AND the thread stays with the bot.

    Delivery still matters (the fixed escalation copy is the employee's only
    route to help), and the no-queue half is now the point: nobody works the
    TingTing OA as a human, so a thread parked in HUMAN mode would wait for an
    agent who will never arrive.
    """
    from app.graph.tingting_guide import tingting_hotline_reply
    from app.services.tingting_api import TingtingApiService

    # The expected reply is built from the STORED setting, not a code constant:
    # the hotline is admin-editable, so the probe asserts exactly what the turn
    # would quote.
    hotline = await TingtingApiService(db).hotline()
    await _assert_persisted_delivery_invariant(
        db,
        conv_id=conv_id,
        message_id=state.pending_message_id,
        expected_reply=tingting_hotline_reply(hotline),
    )
    conv = await db.get(Conversation, conv_id)
    if conv is None:
        raise AssertionError("support-OA hotline probe lost its conversation")
    if conv.mode != ConversationMode.BOT:
        raise AssertionError(f"support OA hotline left the conversation in {conv.mode!s}")
    if conv.needs_human:
        raise AssertionError("support OA hotline queued a human on a non-support question")
    notes = (
        await db.scalars(
            select(Message.body).where(
                Message.conversation_id == conv_id,
                Message.sender == MessageSender.SYSTEM,
            )
        )
    ).all()
    if list(notes):
        raise AssertionError(f"support OA hotline wrote an escalation note: {notes!r}")


async def _check_support_oa_clarify(db, *, conv_id, state) -> None:
    """The bot asked the employee what they need, and kept the thread to answer.

    Asserted together: the question was really delivered, and the thread was NOT
    parked in the human queue (`mode`/`needs_human` untouched, no escalation
    note) — that is what lets the employee's answer start the reset flow.
    """
    await _assert_persisted_delivery_invariant(
        db,
        conv_id=conv_id,
        message_id=state.pending_message_id,
        expected_reply=SMOKE_REPLY,
    )
    conv = await db.get(Conversation, conv_id)
    if conv is None:
        raise AssertionError("support-OA clarify probe lost its conversation")
    if conv.mode != ConversationMode.BOT:
        raise AssertionError(f"support OA clarify left the conversation in {conv.mode!s}")
    if conv.needs_human:
        raise AssertionError("support OA clarify queued a human for an unclear message")
    notes = (
        await db.scalars(
            select(Message.body).where(
                Message.conversation_id == conv_id,
                Message.sender == MessageSender.SYSTEM,
            )
        )
    ).all()
    if list(notes):
        raise AssertionError(f"support OA clarify wrote an escalation note: {notes!r}")


@dataclass(frozen=True)
class _SmokeProbe:
    """One end-to-end turn variant the pre-flip gate runs.

    Every probe wires the real services and the real runner; only the delivery
    path under test differs, so a regression in any of them aborts the flip.
    ``build_deps`` and ``seed`` are resolved by name at call time (the seed
    through a lambda over the module global), which is what lets a test
    substitute either one.
    """

    label: str
    build_deps: Callable[[object], GraphDeps]
    expected_outcome: str
    check: Callable[..., Awaitable[None]]
    seed: Callable[[object], Awaitable[tuple]] = lambda db: _seed_smoke_conversation(db)


# The flip is gated on every probe below. Order matters only for reporting: the
# single-message path runs first so a broad breakage is diagnosed before the
# progressive ones, which assume the same turn machinery works.
_SINGLE_MESSAGE_PROBE = _SmokeProbe(
    label="single-message",
    build_deps=lambda db: _build_smoke_deps(db),
    expected_outcome="sent",
    check=_check_single_message,
)

_PROGRESSIVE_PROBE = _SmokeProbe(
    label="progressive-send",
    build_deps=lambda db: _build_progressive_smoke_deps(db),
    expected_outcome="sent",
    check=_check_progressive_pair,
)

_PROGRESSIVE_FAILURE_PROBE = _SmokeProbe(
    label="progressive-send-failure",
    build_deps=lambda db: _build_failing_progressive_smoke_deps(db),
    expected_outcome="error",
    check=_check_delivered_bubble,
)

# The support OA answers the reset flow only; a confident non-support question
# gets the fixed hotline reply and the thread stays with the bot — nobody is
# queued (operator rule 2026-09-29). Delivery is still asserted: the fixed
# escalation copy is the employee's only route to help.
_SUPPORT_OA_HANDOFF_PROBE = _SmokeProbe(
    label="support-oa-hotline",
    build_deps=lambda db: _build_support_oa_deps(db, intent="faq_detail"),
    expected_outcome="sent",
    check=_check_support_oa_hotline,
    seed=lambda db: _seed_support_oa_conversation(db),
)

# The other half of the same policy: an employee who has NOT said what they need
# must be asked, not queued — the bot keeps the thread so their answer can start
# the reset flow.
_SUPPORT_OA_CLARIFY_PROBE = _SmokeProbe(
    label="support-oa-clarify",
    build_deps=lambda db: _build_support_oa_deps(db, intent="general"),
    expected_outcome="sent",
    check=_check_support_oa_clarify,
    seed=lambda db: _seed_support_oa_conversation(db),
)

SMOKE_PROBES = (
    _SINGLE_MESSAGE_PROBE,
    _PROGRESSIVE_PROBE,
    _PROGRESSIVE_FAILURE_PROBE,
    _SUPPORT_OA_HANDOFF_PROBE,
    _SUPPORT_OA_CLARIFY_PROBE,
)


async def _run_smoke(*, inject_failure: bool) -> int:
    return await _run_probe(_SINGLE_MESSAGE_PROBE, inject_failure=inject_failure)


async def _run_progressive_smoke(*, inject_failure: bool) -> int:
    return await _run_probe(_PROGRESSIVE_PROBE, inject_failure=inject_failure)


async def _run_progressive_failure_smoke(*, inject_failure: bool) -> int:
    return await _run_probe(_PROGRESSIVE_FAILURE_PROBE, inject_failure=inject_failure)


async def _run_support_oa_hotline_smoke(*, inject_failure: bool) -> int:
    return await _run_probe(_SUPPORT_OA_HANDOFF_PROBE, inject_failure=inject_failure)


async def _run_smoke_gate(*, inject_failure: bool) -> int:
    """Run every probe in order; the gate passes only when all of them do.

    Sequential on purpose: the probes share the event loop's exception handler
    and, under ``--inject-failure``, the patched outcome recorder.
    """
    failed: list[str] = []
    for probe in SMOKE_PROBES:
        if await _run_probe(probe, inject_failure=inject_failure) != 0:
            failed.append(probe.label)
    if failed:
        _fail(f"probe(s) failed: {', '.join(failed)}")
        return 1
    return 0


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
    return asyncio.run(_run_smoke_gate(inject_failure=args.inject_failure))


if __name__ == "__main__":
    raise SystemExit(main())
