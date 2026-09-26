"""Think-block stripping for user-visible bot replies.

The pre-send answer review layer that used to live here — ``fast_safety_filter``,
``DeterministicReplyPolicy``, ``truncate_for_chat`` — was removed on explicit
operator instruction: it re-judged and rewrote the agent's answer after
generation (empty-retry, truncation, verdicts) while adding no LLM call worth
its cost. The agent's answer now ships as generated — with one exception that
belongs to generation, not review: a provider that stops at its output cap is
continued (and, failing that, has its dangling tail dropped) inside
``clients.MiniMaxAgent``, so a half-written answer is never delivered. See the
answer-completion guard in ``clients.py``.

One invariant remains: provider reasoning must never reach a candidate.
MiniMax M2 deliberation arrives inline as think blocks inside the content, so
every reply passes through :func:`strip_think_reasoning` exactly once at the
converged boundary in ``runner._finalize_user_visible_reply``.
"""

from __future__ import annotations

import re

# MiniMax M2 reasoning models wrap deliberation in think tags; the user-facing
# reply is what follows the last closing tag. These three patterns are the single
# source of truth for think-block semantics: ``strip_think_reasoning`` removes
# them from the final text, and ``visible_offset`` locates where candidate-visible
# text begins in the raw stream.
_THINK_CLOSE_RE = re.compile(r"</think\s*>", re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<\s*think\b", re.IGNORECASE)
_THINK_TRUNCATED_RE = re.compile(r"<\s*think\b[\s\S]*$", re.IGNORECASE)


def visible_offset(raw: str) -> int | None:
    """Index in ``raw`` where candidate-visible text starts.

    ``0`` when there is no think block, the end of the last closing tag when the
    deliberation is complete, and ``None`` while a think block is still open (the
    stream so far is pure deliberation and nothing is visible yet).
    """
    raw = raw or ""
    matches = list(_THINK_CLOSE_RE.finditer(raw))
    if matches:
        return matches[-1].end()
    if _THINK_OPEN_RE.search(raw):
        return None
    return 0


def strip_think_reasoning(raw: str) -> str:
    """Remove complete or truncated provider reasoning from user-visible text."""
    raw = raw or ""
    if _THINK_CLOSE_RE.search(raw):
        raw = _THINK_CLOSE_RE.split(raw)[-1]
    # A provider timeout can truncate output before the closing tag. In that case
    # everything after the unmatched opener is still deliberation, not a reply.
    # Discard the incomplete block instead of removing only its tag and exposing
    # the reasoning text as user-visible content.
    raw = _THINK_TRUNCATED_RE.sub("", raw)
    return raw
