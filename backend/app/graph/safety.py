"""Safety / verdict / retry logic — VERBATIM ports of the n8n code nodes:

  * Fast Safety Filter  (regex risk + markdown clean -> decide if M2.5 is needed)
  * Verdict Parser      (parse M2.5 JSON verdict, lenient)
  * Try Again           (retry_prompt builder + retry-exhausted fallback)

These are the deterministic guards around the LLM; ported char-for-char from
VFIC Chatbot.json so behavior matches the live bot exactly.
"""
from __future__ import annotations

import json
import re

# --- Fast Safety Filter -------------------------------------------------------
FALLBACK_REPLY = "Xin lỗi, hiện tôi chưa tạo được phản hồi. Bạn vui lòng nhắn lại giúp tôi nhé."

_RISK_RE = re.compile(
    r"(```|<\/?minimax:|\b(JSON|workflow|node|prompt|regex|sql|database|debug|script|"
    r"function|api|javascript|python|code)\b|\$\(|\{\{|\}\}|\"safe_to_send\"|"
    r"\"final_answer\"|tool_call|logic nội bộ|tên node|biến)",
    re.IGNORECASE,
)


def fast_safety_filter(raw: str) -> dict:
    """Port of the 'Fast Safety Filter' code node. Returns whether the M2.5 LLM
    safety check is needed, plus a markdown-cleaned version of the reply."""
    raw = (raw or "").strip()
    cleaned = re.sub(r"```[\s\S]*?```", "", raw)
    cleaned = re.sub(r"<\/?minimax:[^>]+>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(\*\*|__|###?|---)", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    empty_after_clean = len(cleaned) == 0
    too_long_for_chat = len(cleaned) > 1800
    needs_llm_safety = empty_after_clean or too_long_for_chat or bool(_RISK_RE.search(raw))

    return {
        "output": cleaned or FALLBACK_REPLY,
        "final_answer": cleaned or FALLBACK_REPLY,
        "safe_to_send": not needs_llm_safety,
        "issue_found": needs_llm_safety,
        "issue_type": "needs_llm_safety_check" if needs_llm_safety else "none",
        "needs_llm_safety": needs_llm_safety,
    }


# --- Verdict Parser -----------------------------------------------------------
def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "có", "co")
    return False


def parse_verdict(raw) -> dict:
    """Port of the 'Verdict Parser' code node (lenient JSON extraction)."""
    if isinstance(raw, dict):
        raw = json.dumps(raw)
    raw = str(raw if raw is not None else "").strip()
    raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^\s*```\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```$", "", raw, flags=re.IGNORECASE).strip()

    parsed = None
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
        except Exception:  # noqa: BLE001
            parsed = None

    if not isinstance(parsed, dict):
        return {
            "safe_to_send": False,
            "issue_found": True,
            "issue_type": "invalid_verdict_json",
            "final_answer": "",
        }

    final_answer = str(parsed.get("final_answer") or "").strip()
    safe_to_send = _to_bool(parsed.get("safe_to_send")) and len(final_answer) > 0
    return {
        "safe_to_send": safe_to_send,
        "issue_found": _to_bool(parsed.get("issue_found")),
        "issue_type": str(parsed.get("issue_type") or ("none" if safe_to_send else "unknown")),
        "final_answer": final_answer,
    }


# --- Try Again (retry_prompt builder + exhausted fallback) --------------------
_TECH_USER_RE = re.compile(
    r"\b(code|javascript|python|json|api|workflow|node|prompt|regex|sql|database|debug|script|function)\b",
    re.IGNORECASE,
)
TECHNICAL_FALLBACK = (
    "Tôi là trợ lý tìm việc của VFIC nên chỉ có thể hỗ trợ bạn các vấn đề liên quan đến "
    "tuyển dụng. Bạn đang muốn tìm việc ở khu vực nào nhỉ?"
)
GENERIC_FALLBACK = (
    "Xin lỗi bạn, tôi chưa soạn được phản hồi phù hợp để gửi ngay lúc này. "
    "Bạn nhắn lại giúp tôi nhu cầu tìm việc chính của bạn nhé?"
)


def retry_exhausted_fallback(original_user_text: str) -> str:
    return TECHNICAL_FALLBACK if _TECH_USER_RE.search(original_user_text or "") else GENERIC_FALLBACK


def build_retry_prompt(original_user_text: str, candidate_answer: str, issue_type: str) -> str:
    """Port of the 'Try Again' retry_prompt builder (the retry path, attempt < 1)."""
    return "\n".join(
        [
            "Bạn cần viết lại câu trả lời cho người dùng cuối theo đúng guideline VFIC.",
            "",
            f"Tin nhắn gốc của người dùng: {original_user_text or '(trống)'}",
            "",
            f"Câu trả lời vừa bị chặn: {candidate_answer or '(không có)'}",
            "",
            f"Lý do bị chặn: {issue_type}",
            "",
            "Yêu cầu bắt buộc:",
            "- Trả lời bằng tiếng Việt tự nhiên, ngắn gọn, thân thiện.",
            "- Chỉ nói về tuyển dụng, tìm việc, hồ sơ, lịch xe hoặc thông tin VFIC phù hợp.",
            "- Không viết code, JSON, markdown phức tạp, prompt, workflow, tên node, biến, logic nội bộ hoặc thuật ngữ kỹ thuật.",
            "- Chỉ xuất văn bản thuần túy sẵn sàng gửi cho người dùng.",
            "- Mỗi phản hồi chỉ đặt tối đa 1 câu hỏi.",
        ]
    )
