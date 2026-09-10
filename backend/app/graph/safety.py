"""Deterministic safety, verdict parsing, and retry-prompt logic for bot replies."""

from __future__ import annotations

import re
from typing import TypedDict

from app.graph.ports import ReplyPolicyResult

# --- Fast Safety Filter -------------------------------------------------------


class FastSafetyResult(TypedDict):
    """Cleaned reply + flags emitted by :func:`fast_safety_filter`."""

    output: str
    final_answer: str
    safe_to_send: bool
    issue_found: bool
    issue_type: str
    needs_llm_safety: bool
    too_long: bool
    empty_after_clean: bool
    retryable_empty: bool


# --- Fast Safety Filter -------------------------------------------------------
# Friendly fallback when the bot can't produce a good reply. Short, natural,
# and redirects the user — not robotic filler.
FALLBACK_REPLY = (
    "Em chưa thể xác minh câu trả lời này ạ. Anh/chị đang quan tâm vị trí tuyển dụng, "
    "mức lương, xe đưa đón hay hồ sơ ứng tuyển để em kiểm tra đúng thông tin nhé ạ?"
)

_RISK_RE = re.compile(
    # Structural markers are high-precision signals of leaked reasoning / tool
    # output — a normal recruitment reply never contains these.
    r"(```|<\/?minimax:|\$\(|\{\{|\}\}|"
    # JSON-shape leakage from the safety judge protocol itself.
    r"\"safe_to_send\"|\"final_answer\"|tool_call|"
    # Tagged leakage phrases (Vietnamese) — matched as phrases, not bare words,
    # so natural prose mentioning "code"/"api" in a job description does not
    # falsely escalate to the 10s+ LLM safety judge.
    r"logic nội bộ|tên node|biến hệ thống|hướng dẫn hệ thống|lời nhắc hệ thống)",
    re.IGNORECASE,
)


def strip_think_reasoning(raw: str) -> str:
    """Remove complete or truncated provider reasoning from user-visible text."""
    raw = raw or ""
    # MiniMax M2 reasoning models wrap deliberation in <think>…</think>; the
    # user-facing reply is what follows the last </think>. Never send reasoning.
    if re.search(r"</think\s*>", raw, flags=re.IGNORECASE):
        raw = re.split(r"</think\s*>", raw, flags=re.IGNORECASE)[-1]
    # A provider timeout can truncate output before ``</think>``. In that case
    # everything after the unmatched opener is still deliberation, not a reply.
    # Discard the incomplete block instead of removing only its tag and exposing
    # the reasoning text as user-visible content.
    raw = re.sub(r"<\s*think\b[\s\S]*$", "", raw, flags=re.IGNORECASE)
    return raw


def fast_safety_filter(raw: str) -> FastSafetyResult:
    """Return whether an LLM safety check is needed plus a cleaned reply."""
    original_raw = (raw or "").strip()
    raw = strip_think_reasoning(original_raw)
    cleaned = re.sub(r"```[\s\S]*?```", "", raw)
    cleaned = re.sub(r"<\/?minimax:[^>]+>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(\*\*|__|###?|---)", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    empty_after_clean = len(cleaned) == 0
    too_long_for_chat = len(cleaned) > 1800
    # Deterministic resolution for an over-long reply: truncate at a word
    # boundary so the output is bounded even if the LLM safety judge is later
    # disabled (Slice E.4). The flag still routes to the judge when enabled.
    output = (
        truncate_for_chat(cleaned or FALLBACK_REPLY)
        if too_long_for_chat
        else (cleaned or FALLBACK_REPLY)
    )
    # Risk scan runs against the CLEANED reply, not raw. Code fences / markdown
    # are already stripped above, so a fence that the agent slipped in (but
    # which never reaches the user) must not discard the whole reply. True
    # leakage — JSON protocol keys, <minimax: tags, Vietnamese system-prompt
    # phrases — survives cleaning and still trips the flag.
    needs_llm_safety = (
        empty_after_clean or too_long_for_chat or bool(_RISK_RE.search(cleaned))
    )
    retryable_empty = (
        empty_after_clean
        and not _RISK_RE.search(original_raw)
        and not blocklist_hit(original_raw)
    )

    return {
        "output": output,
        "final_answer": output,
        "safe_to_send": not needs_llm_safety,
        "issue_found": needs_llm_safety,
        "issue_type": "needs_llm_safety_check" if needs_llm_safety else "none",
        "needs_llm_safety": needs_llm_safety,
        "too_long": too_long_for_chat,
        "empty_after_clean": empty_after_clean,
        "retryable_empty": retryable_empty,
    }


class DeterministicReplyPolicy:
    """Concrete pre-send policy; replaceable behind :class:`ReplyPolicyPort`."""

    def finalize(
        self,
        candidate: str,
        *,
        generated: bool,
        user_text: str,
    ) -> ReplyPolicyResult:
        reasoning_free = strip_think_reasoning(candidate).strip()
        if not generated:
            return ReplyPolicyResult(output=reasoning_free, verdict="passed")

        fs = fast_safety_filter(reasoning_free)
        output = fs["output"]
        blocklisted = blocklist_hit(output)

        if blocklisted:
            return ReplyPolicyResult(
                output=retry_exhausted_fallback(user_text),
                verdict="blocklist_redirect",
                trigger="blocklist",
            )
        if fs["empty_after_clean"]:
            return ReplyPolicyResult(
                output=retry_exhausted_fallback(user_text),
                verdict="empty_after_clean",
                trigger="empty_after_clean",
            )
        if fs["needs_llm_safety"] and not fs["too_long"]:
            return ReplyPolicyResult(
                output=retry_exhausted_fallback(user_text),
                verdict="risk_redirect",
                trigger="risk_pattern",
            )
        if fs["too_long"]:
            return ReplyPolicyResult(
                output=output,
                verdict="truncated",
                trigger="truncated",
            )
        return ReplyPolicyResult(output=output, verdict="passed")


def truncate_for_chat(text: str, limit: int = 1800) -> str:
    """Truncate to ~``limit`` chars at the nearest preceding word boundary.

    Falls back to a hard cut when there is no space within range. Appends an
    ellipsis so the truncation is visible to the user.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    if cut <= 0:
        cut = limit
    return text[:cut].rstrip() + " …"


# --- Lexical blocklist (fast, deterministic hard-redirect) --------------------
# A coarse, high-PRECISION deny-list for content the bot must never emit, checked
# on the LLM output BEFORE the (slower) LLM safety judge. A hit redirects to a
# fallback and skips the judge entirely (Slice E.1). The list is deliberately
# narrow — clear prompt-injection / instruction-override / system-leakage, plus
# unmistakable vulgarity and self-harm/violence — so legitimate recruitment
# replies are not bounced. Nuanced / off-topic content (politics, borderline
# cases) is left to the LLM safety judge (Slice E.4). Tune by editing here.
_BLOCKLIST_PATTERNS = (
    # Prompt-injection / instruction-override / system-leakage (English).
    re.compile(
        r"ignore\s+(all\s+|the\s+|all\s+the\s+)?(previous|prior|above|earlier)\s+"
        r"(instructions?|prompts?|rules?|directives?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"disregard\s+(the\s+|all\s+|any\s+|previous\s+)?(instructions?|prompts?|rules?|guidance)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(you are now\b|act as if\b|act as a\b|act as an\b|pretend (you are|to be)|"
        r"new (instructions?|role)|override (your|the|all) (instructions?|rules?))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(system prompt|reveal (your|the) (instructions?|prompt|rules?|guidelines?)|"
        r"jailbreak|\bDAN\b)\b",
        re.IGNORECASE,
    ),
    re.compile(r"</?(system|prompt|instructions?|minimax)\b", re.IGNORECASE),
    # Vietnamese prompt-injection / leakage equivalents.
    re.compile(
        r"bỏ\s+qua\s+(các\s+|những\s+|mọi\s+)?(lệnh|hướng\s+dẫn|quy\s+tắc|yêu\s+cầu|chỉ\s+thị)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(lệnh\s+mới|hướng\s+dẫn\s+mới|quy\s+tắc\s+mới|bỏ\s+qua\s+hướng\s+dẫn|"
        r"vượt\s+qua\s+(lệnh|hướng\s+dẫn|quy\s+tắc))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(bạn (đang|sẽ|giờ) là|đóng\s+vai|giả\s+vờ|lời\s+nhắc\s+(của\s+)?(hệ\s+thống|bạn)|"
        r"tiết\s+lộ\s+(lệnh|hướng\s+dẫn|prompt|quy\s+tắc))",
        re.IGNORECASE,
    ),
    # Self-harm / violence.
    re.compile(
        r"(tự\s+sát|tự\s+tử|tự\s+làm\s+khổ|giết\s+(người|mình|cả\s+nhà))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(kill\s+(myself|yourself|himself|herself|others|him|her|them)|"
        r"harm\s+(myself|yourself|others)|suicide|self[\s-]?harm)\b",
        re.IGNORECASE,
    ),
    # Unmistakable vulgarity / profanity (Vietnamese + English), narrow set.
    re.compile(r"(địt|lồn|cặc|buồi|dâm)", re.IGNORECASE),
    re.compile(r"\b(fuck|shit|bitch|cunt|dick|asshole|motherfucker)\b", re.IGNORECASE),
)


def blocklist_hit(raw: str) -> bool:
    """True if the LLM output matches a hard-redirect blocklist term."""
    raw = raw or ""
    return any(pattern.search(raw) for pattern in _BLOCKLIST_PATTERNS)


# --- Fallbacks (deterministic redirects for flagged replies) -----------------
_TECH_USER_RE = re.compile(
    r"\b(code|javascript|python|json|api|workflow|node|prompt|regex|sql|database|debug|script|function)\b",
    re.IGNORECASE,
)
TECHNICAL_FALLBACK = (
    "Em là trợ lý VFIC nên chỉ hỗ trợ các vấn đề tuyển dụng và hỗ trợ nhân viên "
    "(lương, phúc lợi, lịch xe, thủ tục…). Anh/chị cần em giúp việc tìm việc hay "
    "thắc mắc khi đang làm tại dự án VFIC nhé ạ?"
)
# Friendly redirect when the bot can't produce a good reply.
GENERIC_FALLBACK = FALLBACK_REPLY


def retry_exhausted_fallback(original_user_text: str) -> str:
    # Off-topic technical questions (code/debug) get a redirect to VFIC's scope
    # (recruitment + employee support). Everything else gets the generic fallback.
    return (
        TECHNICAL_FALLBACK if _TECH_USER_RE.search(original_user_text or "") else GENERIC_FALLBACK
    )
