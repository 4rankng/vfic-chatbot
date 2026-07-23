"""Prompt-context assembly for chatbot turns."""

from __future__ import annotations

from typing import Any

from app.graph.message_values import delivery_is, sender_is
from app.graph.types import _speaker


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
        history_lines = [f"- {_speaker(m)}: {m.body.strip()}" for m in history]
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
