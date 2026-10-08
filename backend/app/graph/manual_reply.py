"""The recruiter-triggered "read the conversation, reply only if needed" turn.

A recruiter watching the console can see a thread the candidate is waiting on
that no pending-inbound nudge can fix: the last inbound was already answered
(``😊``), so ``force-bot-reply`` refuses with "không có tin nhắn nào đang chờ",
yet the candidate clearly still needs a real answer. This module owns that
turn's contract.

The turn runs through the normal pipeline — same gates, same agent lane, same
claim/dispatch unit — with two differences that make it a *review* rather than a
*reply*:

1. There is no new inbound message. ``user_text`` is empty, so routing falls to
   the neutral general/agent route and the agent reads the conversation history
   as its input (see ``prompt_context.build_agent_user_text``).
2. The agent is told it may stay silent. Silence is a first-class outcome, not a
   failure: it is signalled with :data:`NO_REPLY_SENTINEL`, which the lane turns
   into a ``manual_skip`` suppression that sends nothing to the candidate.

The directive text lives here — with the sentinel that implements it — rather
than in the enqueueing scheduler, so ``app.services`` never has to import the
turn runtime to describe a turn. Jobs carry the boolean flag ``manual_turn``
instead; the worker resolves the text.
"""

from __future__ import annotations

import re

from app.graph.types import BotRunState

# The one string the agent may return to say "this conversation needs no reply".
# It never reaches a candidate: the lane turns it into a suppression.
NO_REPLY_SENTINEL = "NO_REPLY"

# The mandatory instruction the agent lane receives for a manual turn. It rides
# in the same slot as the multi-project clarification instruction (both are
# "KẾ HOẠCH ĐIỀU PHỐI" overrides), but the manual one wins: there is no
# candidate message to disambiguate projects against, and deciding whether to
# answer at all is the whole point of the turn.
MANUAL_REPLY_INSTRUCTION = (
    "LƯỢT XEM LẠI DO NHÂN VIÊN YÊU CẦU: ứng viên không gửi tin nhắn mới. "
    "Hãy đọc toàn bộ lịch sử hội thoại và quyết định có cần gửi tin nhắn tiếp cho ứng viên không.\n"
    "- CẦN gửi khi: ứng viên đang chờ một câu trả lời cụ thể, hội thoại bị bỏ ngỏ giữa chừng, "
    "hoặc tin nhắn cuối của bạn chỉ là phản hồi rất ngắn (ví dụ một biểu tượng cảm xúc) "
    "trong khi ứng viên vẫn cần thông tin.\n"
    "- KHÔNG gửi khi: ứng viên đã được trả lời đầy đủ, cuộc trò chuyện đã kết thúc lịch sự, "
    "hoặc bạn không có gì mới để nói. Không gửi để 'cho có', không lặp lại điều đã nói.\n"
    f"- Nếu không cần gửi, trả lời duy nhất bằng chuỗi: {NO_REPLY_SENTINEL} "
    "và không viết thêm gì. Khi đó hệ thống sẽ không gửi tin nhắn nào cho ứng viên."
)

# Accepts the sentinel however the model wraps or trails it — ``**NO_REPLY**``,
# ``no_reply.``, ``NO_REPLY - không cần``. Only the first token is compared, so
# a genuine Vietnamese reply (whose first word is never this token) cannot be
# mistaken for a skip. The separator is dropped rather than required, because
# failing to recognize the sentinel would send that literal text to a candidate.
_HEAD_NOISE = re.compile(r"^[\s*_`\"'“”‘’(\[]+")
_TOKEN_NOISE = re.compile(r"[*_`\"'“”‘’(\[\]]+")
_FIRST_TOKEN = re.compile(r"[\s,.:;!?…—–\-)\]]+")


def is_manual_turn(state: BotRunState) -> bool:
    """Whether this turn was requested by a recruiter from the console."""
    return bool((getattr(state, "manual_instruction", "") or "").strip())


def manual_instruction_for(manual_turn: object) -> str:
    """Resolve a job's ``manual_turn`` flag into the agent's directive.

    The job dict is the only thing that crosses the queue boundary, and the
    flag is what it carries; the directive text never leaves this module.
    """
    return MANUAL_REPLY_INSTRUCTION if manual_turn else ""


def manual_skip_requested(reply: str) -> bool:
    """Whether the agent asked for silence instead of a reply."""
    head = _HEAD_NOISE.sub("", (reply or "").strip())
    if not head:
        return False
    first = _FIRST_TOKEN.split(head, maxsplit=1)[0]
    return _TOKEN_NOISE.sub("", first).upper() == "NOREPLY"