"""Message + BotRun fixture: turns the seeded conversations into chat threads.

The thread bodies themselves live in :mod:`scripts.seed.message_scripts`; this
module only decides which script each conversation gets and when its lines
land, plus the BotRun that accompanies every bot reply.
"""

from __future__ import annotations

from datetime import timedelta

from app.models.conversation import (
    BotRun,
    BotRunOutcome,
    Conversation,
    ConversationMode,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.user import User

from .common import rng
from .message_scripts import CONVERSATION_SCRIPTS, RECRUITER_SCRIPTS


def make_messages_and_bot_runs(
    convos: list[Conversation],
    users: list[User],
) -> tuple[list[Message], list[BotRun]]:
    messages: list[Message] = []
    bot_runs: list[BotRun] = []

    # Thread bodies come from scripts.seed.message_scripts: the bot-handled
    # scripts, plus the recruiter takeover scripts for HUMAN/SEMI_AUTO threads.
    for i, conv in enumerate(convos):
        if conv.mode in (ConversationMode.HUMAN, ConversationMode.SEMI_AUTO):
            script = RECRUITER_SCRIPTS[i % len(RECRUITER_SCRIPTS)]
        else:
            script = CONVERSATION_SCRIPTS[i % len(CONVERSATION_SCRIPTS)]

        base_time = conv.created_at + timedelta(minutes=rng.randint(1, 30))
        for j, (sender, body) in enumerate(script):
            t = base_time + timedelta(minutes=j * rng.randint(2, 15), seconds=rng.randint(0, 59))
            msg = Message(
                conversation_id=conv.id,
                sender=sender,
                body=body,
                delivery_status=DeliveryStatus.SENT,
                created_at=t,
            )
            if sender == MessageSender.RECRUITER:
                msg.recruiter_id = conv.assigned_recruiter_id
            messages.append(msg)

            # Create a BotRun for each BOT message
            if sender == MessageSender.BOT:
                run = BotRun(
                    conversation_id=conv.id,
                    started_at=t - timedelta(seconds=rng.randint(5, 45)),
                    ended_at=t,
                    version_at_start=conv.version,
                    proposed_reply=body,
                    outcome=BotRunOutcome.SENT,
                )
                bot_runs.append(run)
                msg.bot_run_id = run.id

    return messages, bot_runs
