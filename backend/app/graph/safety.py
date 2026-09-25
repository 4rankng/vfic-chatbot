"""Think-block stripping for user-visible bot replies.

The pre-send answer review layer that used to live here — ``fast_safety_filter``,
``DeterministicReplyPolicy``, ``truncate_for_chat`` — was removed on explicit
operator instruction: it re-judged and rewrote the agent's answer after
generation (empty-retry, truncation, verdicts) while adding no LLM call worth
its cost. The agent's answer now ships as generated.

One invariant remains: provider reasoning must never reach a candidate.
MiniMax M2 deliberation arrives inline as think blocks inside the content, so
every reply passes through :func:`strip_think_reasoning` exactly once at the
converged boundary in ``runner._finalize_user_visible_reply``.
"""

from __future__ import annotations

import re


def strip_think_reasoning(raw: str) -> str:
    """Remove complete or truncated provider reasoning from user-visible text."""
    raw = raw or ""
    # MiniMax M2 reasoning models wrap deliberation in think tags; the
    # user-facing reply is what follows the last closing tag. Never send reasoning.
    if re.search(r"</think\s*>", raw, flags=re.IGNORECASE):
        raw = re.split(r"</think\s*>", raw, flags=re.IGNORECASE)[-1]
    # A provider timeout can truncate output before the closing tag. In that case
    # everything after the unmatched opener is still deliberation, not a reply.
    # Discard the incomplete block instead of removing only its tag and exposing
    # the reasoning text as user-visible content.
    raw = re.sub(r"<\s*think\b[\s\S]*$", "", raw, flags=re.IGNORECASE)
    return raw
