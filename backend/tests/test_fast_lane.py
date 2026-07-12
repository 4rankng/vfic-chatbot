"""Unit tests for app/graph/fast_lane — the deterministic non-factual router.

Pins the route table (greeting / thanks / goodbye / help / fall-through) and the
persona-voice invariant (tôi/bạn, never em/anh/chị) on every canned template.
Feeds Slice F's broader persona-voice guard.
"""

from __future__ import annotations

import re

import pytest

from app.graph.fast_lane import (
    GOODBYE_REPLY,
    GREETING_REPLY,
    HELP_REPLY,
    THANKS_REPLY,
    match,
)

# Address pronouns. Tokenized (Unicode-aware) so "xem"/"chính"/"gửi" never trip
# the em/anh/chị check — only a standalone pronoun token does.
_BANNED_ADDRESS = {"em", "anh", "chị", "chi"}


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text, flags=re.UNICODE)


def _assert_persona_voice(reply: str) -> None:
    tokens = _tokens(reply)
    assert "bạn" in tokens or "tôi" in tokens, f"missing tôi/bạn in: {reply!r}"
    bad = _BANNED_ADDRESS & set(tokens)
    assert not bad, f"banned address pronoun(s) {bad} in: {reply!r}"


@pytest.mark.parametrize(
    ("text", "intent", "reply"),
    [
        ("hi", "greeting", GREETING_REPLY),
        ("Chào bạn!", "greeting", GREETING_REPLY),
        ("XIN CHÀO", "greeting", GREETING_REPLY),
        ("cảm ơn bạn nhe", "thanks", THANKS_REPLY),
        ("tạm biệt", "goodbye", GOODBYE_REPLY),
        ("bạn giúp gì được", "help", HELP_REPLY),
    ],
)
def test_match_routes_non_factual_traffic(text, intent, reply):
    hit = match(text)
    assert hit is not None
    assert hit.intent == intent
    assert hit.reply == reply
    _assert_persona_voice(hit.reply)


@pytest.mark.parametrize(
    "text",
    [
        "lương bao nhiêu",
        "tôi muốn lái xe",
        "có xe đưa đón không",
        "",  # empty → fall through
        "????",  # only punctuation → fall through
    ],
)
def test_match_falls_through_factual_or_empty(text):
    """Factual questions and empty input must NOT be templated — they reach the
    RAG + agent path (no fake-data hardcoded answers)."""
    assert match(text) is None


def test_all_canned_templates_use_persona_voice():
    """Every exported template satisfies the tôi/bạn invariant, including any
    added in the future (the regression net for persona drift)."""
    for reply in (GREETING_REPLY, THANKS_REPLY, GOODBYE_REPLY, HELP_REPLY):
        _assert_persona_voice(reply)


def test_greeting_with_factual_clause_is_not_swallowed():
    """A greeting that also carries a real question must fall through — the fast
    lane never answers a factual question with a greeting template."""
    assert match("chào bạn, lương bao nhiêu?") is None
