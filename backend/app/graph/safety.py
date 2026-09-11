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
# Structural cleaning and length bounding only. A reply with nothing sendable
# stays empty; the caller keeps quiet rather than sending a canned deflection.

# Lexical content filtering was removed deliberately. Keyword and phrase regexes
# cannot tell an injection echo from ordinary Vietnamese: "đóng vai trò" (plays a
# role), "lồng ghép" (contains the profanity substring "lồn"), "bỏ qua yêu cầu
# bằng cấp" (waives the qualification requirement) and "hướng dẫn mới" are all
# everyday recruitment prose. Every match discarded a complete, tool-grounded
# answer and sent a content-free hedge instead, which is a worse outcome than the
# text the filter was guarding against.
#
# What remains here is structural, not lexical: strip provider reasoning, strip
# markup, bound the length. Those operate on the shape of the output and cannot
# false-positive on the meaning of a sentence.


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
    raw = strip_think_reasoning((raw or "").strip())
    cleaned = re.sub(r"```[\s\S]*?```", "", raw)
    cleaned = re.sub(r"<\/?minimax:[^>]+>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(\*\*|__|###?|---)", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    empty_after_clean = len(cleaned) == 0
    too_long_for_chat = len(cleaned) > 1800
    # Deterministic resolution for an over-long reply: truncate at a word
    # boundary so the output is always bounded for chat transport. An empty
    # reply stays empty — the caller decides to keep quiet.
    output = truncate_for_chat(cleaned) if too_long_for_chat else cleaned
    # Only structural conditions flag a reply now: nothing survived cleaning, or
    # it exceeds the chat length bound. Content is never judged by keyword.
    needs_llm_safety = empty_after_clean or too_long_for_chat
    # An empty reply is always worth one regeneration attempt; there is no longer
    # a lexical reason to treat some empties as non-retryable.
    retryable_empty = empty_after_clean

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

        if fs["empty_after_clean"]:
            # Nothing sendable survived cleaning. The bot keeps quiet rather
            # than inventing a redirect: output stays empty and the caller
            # (runner/worker) suppresses the turn instead of sending.
            return ReplyPolicyResult(
                output="",
                verdict="empty_after_clean",
                trigger="empty_after_clean",
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


# A reply that produced no sendable text sends NOTHING: the runner records the
# turn as SUPPRESSED (see ``_record_silent_terminal``) instead of persisting a
# placeholder bubble. Keep-quiet beats a canned deflection.
