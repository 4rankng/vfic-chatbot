"""Prompt-context assembly for chatbot turns."""

from __future__ import annotations

from typing import Any

from app.graph.message_values import delivery_is, sender_is
from app.graph.types import _speaker

# The direct-context lane caps its injected history at 12_000 tokens; this agent
# lane previously injected up to 16 recent messages with no budget at all, so a
# burst of long candidate messages could dominate the prompt. Bound the rendered
# history by characters, keep the NEWEST turns (drop the oldest whole first),
# and mark the elision so the model knows older context was dropped.
_MAX_HISTORY_CHARS = 6000
_HISTORY_ELISION_MARKER = (
    "- [... đã lược bỏ {count} tin nhắn cũ hơn do giới hạn ngữ cảnh]"
)
_HISTORY_TRUNCATION_SUFFIX = " …[rút gọn]"


def _bounded_history_lines(history: list[Any]) -> list[str]:
    """Render recent messages within ``_MAX_HISTORY_CHARS``, newest kept.

    Renders oldest→newest as before, drops the oldest whole messages until the
    budget fits, then truncates the single oldest survivor if it alone is over
    budget. Prepends an elision marker when anything was dropped. ``history``
    never contains the current candidate message (the caller appends it
    separately), so truncation here can never cut the current user message.
    """
    lines = [f"- {_speaker(m)}: {m.body.strip()}" for m in history]
    total = sum(len(line) + 1 for line in lines)
    elided = 0
    while len(lines) > 1 and total > _MAX_HISTORY_CHARS:
        total -= len(lines.pop(0)) + 1
        elided += 1
    if lines and total > _MAX_HISTORY_CHARS:
        room = max(_MAX_HISTORY_CHARS - len(_HISTORY_TRUNCATION_SUFFIX), 0)
        lines[-1] = lines[-1][:room] + _HISTORY_TRUNCATION_SUFFIX
    if elided:
        lines.insert(0, _HISTORY_ELISION_MARKER.format(count=elided))
    return lines


def build_agent_user_text(
    *,
    chat_id: str,
    current_user_text: str,
    recent_messages: list[Any],
    lead_profile: str = "",
    lead_collection_instruction: str = "",
    route_hint: str = "",
) -> str:
    """Give the agent the actual chat state, not just the latest short reply."""
    history = [
        m
        for m in recent_messages
        if (m.body or "").strip() and not delivery_is(m, "SUPPRESSED")
    ]
    if (
        history
        and sender_is(history[-1], "WORKER")
        and history[-1].body.strip() == current_user_text.strip()
    ):
        history = history[:-1]

    if history:
        history_lines = _bounded_history_lines(history)
    else:
        history_lines = ["- (chưa có tin nhắn trước đó)"]

    parts: list[str] = [
        f"CHAT_ID để tra cứu memory khi cần: {chat_id}",
    ]
    if lead_profile:
        parts += ["", lead_profile]
    if route_hint:
        parts += ["", "KẾ HOẠCH ĐIỀU PHỐI:", route_hint]
    if lead_collection_instruction:
        parts += ["", lead_collection_instruction]
    parts += [
        "",
        "LỊCH SỬ GẦN ĐÂY (cũ -> mới):",
        *history_lines,
        "",
        "TIN NHẮN HIỆN TẠI CỦA ỨNG VIÊN:",
        current_user_text,
        "",
        "NGỮ CẢNH RIÊNG TƯ: lịch sử, hồ sơ và memory chỉ để hiểu ngữ cảnh. "
        "Không được trích dẫn, tóm tắt hoặc nhắc rằng bạn biết các thông tin đó; "
        "không gọi người dùng là 'ứng viên trước đó' và không nói 'theo memory/lịch sử'.",
        "",
        "Hãy trả lời tin nhắn hiện tại dựa trên lịch sử trên. "
        "Nếu đây là câu trả lời ngắn cho câu hỏi trước đó, tiếp tục đúng mạch hội thoại; "
        "không chào lại hoặc hỏi lại thông tin đã có.",
    ]
    return "\n".join(parts)
