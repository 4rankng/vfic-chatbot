"""Persona-voice invariant guard (plan test #14).

Every bot-visible static reply string — error/timeout/slow-ack/fallback/degradation
constants + the deterministic fast-lane templates — must address the user as
**bạn** and self as **tôi**, NEVER em/anh/chị (persona.md:40). This is the net
that catches hand-authored drift on the constants (LLM output is already bound
via AGENT_SYSTEM_PROMPT).

Tokenization is Unicode-aware so "xem"/"gửi"/"chính"/"nhanh" never trip the
em/anh/chị check — only a standalone pronoun token does.
"""
from __future__ import annotations

import re

import pytest

from app.graph.fast_lane import (
    GOODBYE_REPLY,
    GREETING_REPLY,
    HELP_REPLY,
    THANKS_REPLY,
)
from app.graph.prompts import ERROR_REPLY, SLOW_ACK_REPLY, TIMEOUT_REPLY
from app.graph.safety import FALLBACK_REPLY, GENERIC_FALLBACK, TECHNICAL_FALLBACK
from app.workers.chatbot_worker import DEGRADATION_REPLY

# Every bot-visible static reply string. A rename/removal here fails the build,
# which is the intent: no constant escapes the invariant.
STATIC_REPLIES = {
    "ERROR_REPLY": ERROR_REPLY,
    "TIMEOUT_REPLY": TIMEOUT_REPLY,
    "SLOW_ACK_REPLY": SLOW_ACK_REPLY,
    "FALLBACK_REPLY": FALLBACK_REPLY,
    "TECHNICAL_FALLBACK": TECHNICAL_FALLBACK,
    "GENERIC_FALLBACK": GENERIC_FALLBACK,
    "DEGRADATION_REPLY": DEGRADATION_REPLY,
    "GREETING_REPLY": GREETING_REPLY,
    "THANKS_REPLY": THANKS_REPLY,
    "GOODBYE_REPLY": GOODBYE_REPLY,
    "HELP_REPLY": HELP_REPLY,
}

# The persona invariant bans em/anh/chị as address pronouns (persona.md:40).
# Only standalone pronoun tokens are flagged — Vietnamese is isolating, so "em"
# / "anh" / "chị" as tokens are the address forms (not substrings of "xem" etc.).
_BANNED_ADDRESS_PRONOUNS = {"em", "anh", "chị"}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text or "", flags=re.UNICODE))


@pytest.mark.parametrize("name", sorted(STATIC_REPLIES))
def test_static_reply_uses_persona_voice(name):
    reply = STATIC_REPLIES[name]
    tokens = _tokens(reply)
    assert "bạn" in tokens or "tôi" in tokens, (
        f"{name} must address the user as bạn / self as tôi: {reply!r}"
    )
    leaked = _BANNED_ADDRESS_PRONOUNS & tokens
    assert not leaked, f"{name} uses banned address pronoun(s) {leaked}: {reply!r}"


def test_no_static_reply_is_empty():
    """An empty constant would silently send nothing — guard against it too."""
    for name, reply in STATIC_REPLIES.items():
        assert reply and reply.strip(), f"{name} is empty"
