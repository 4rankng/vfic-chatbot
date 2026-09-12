"""Persona-voice invariant guard.

Every bot-visible static reply string — error/timeout/slow-ack/fallback/degradation
constants + the deterministic fast-lane templates — must refer to the bot as
**em** and address the user as **anh/chị**, NEVER bạn/tôi/mình (persona.md).
This is the net that catches hand-authored drift on the constants (LLM output is
already bound via AGENT_SYSTEM_PROMPT).

Every one of these strings is emitted before any lead lookup, so the candidate's
gender is never known on these paths. They must therefore use the neutral
"anh/chị" — a bare "anh" or "chị" here would be a coin-flip guess at the user's
gender, which is exactly what the address-form plumbing exists to avoid.

Tokenization is Unicode-aware so "xem"/"gửi"/"chính"/"nhanh" never trip the
pronoun check — only a standalone pronoun token does.
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
from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.services.lead.normalizers import address_form, lead_profile_text

# Every bot-visible static reply string. A rename/removal here fails the build,
# which is the intent: no constant escapes the invariant. (Error-class paths no
# longer carry a static reply: a crashed agent, an exhausted provider chain, or
# an empty/unverifiable reply keeps quiet — the failure goes to the structured
# log, never to a candidate. TIMEOUT_REPLY was deleted: the turn deadline is
# advisory (typing pulses instead) and the constant was never sent.)
STATIC_REPLIES = {
    "GREETING_REPLY": GREETING_REPLY,
    "THANKS_REPLY": THANKS_REPLY,
    "GOODBYE_REPLY": GOODBYE_REPLY,
    "HELP_REPLY": HELP_REPLY,
}

# The persona invariant bans bạn/tôi/mình as pronouns (persona.md). Only
# standalone tokens are flagged — Vietnamese is isolating, so these as tokens
# are the pronoun forms (not substrings of "xem", "bạng", etc.).
_BANNED_PRONOUNS = {"bạn", "tôi", "mình", "Bạn", "Tôi", "Mình"}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text or "", flags=re.UNICODE))


@pytest.mark.parametrize("name", sorted(STATIC_REPLIES))
def test_static_reply_uses_persona_voice(name):
    reply = STATIC_REPLIES[name]
    lowered = {token.lower() for token in _tokens(reply)}
    assert "em" in lowered, f"{name} must refer to the bot as em: {reply!r}"
    leaked = {token.lower() for token in _BANNED_PRONOUNS} & lowered
    assert not leaked, f"{name} uses banned pronoun(s) {leaked}: {reply!r}"


@pytest.mark.parametrize("name", sorted(STATIC_REPLIES))
def test_static_reply_addresses_user_neutrally(name):
    """No static reply may guess the user's gender.

    These strings all predate any lead lookup, so "anh" or "chị" on its own
    would be an unfounded guess. Only the joined "anh/chị" form is allowed.
    """
    reply = STATIC_REPLIES[name]
    neutral_stripped = reply.replace("anh/chị", "").replace("Anh/chị", "")
    stray = {"anh", "chị"} & {token.lower() for token in _tokens(neutral_stripped)}
    assert not stray, (
        f"{name} uses a gendered address form {stray} outside 'anh/chị'; "
        f"gender is unknown on this path: {reply!r}"
    )
    assert "anh/chị" in reply.lower(), (
        f"{name} must address the user as anh/chị: {reply!r}"
    )


@pytest.mark.parametrize(
    ("gender", "expected"),
    [
        ("male", "anh"),
        ("female", "chị"),
        ("MALE", "anh"),
        ("  female  ", "chị"),
        (None, "anh/chị"),
        ("", "anh/chị"),
        ("unknown", "anh/chị"),
        # Vietnamese spellings are NOT provider values — Facebook returns
        # male/female. Anything else must stay neutral rather than guess.
        ("nam", "anh/chị"),
        ("nữ", "anh/chị"),
    ],
)
def test_address_form_mapping(gender, expected):
    """Gender resolves to an address form; anything unrecognised stays neutral."""
    assert address_form(gender) == expected


def test_lead_profile_text_always_carries_an_address_form():
    """Every turn needs an address form, including brand-new leads.

    The block sits outside the ``personalize`` flag on purpose: that flag is
    Zalo-OA-only, so gating on it would leave Messenger turns with no address
    guidance at all.
    """
    assert "XƯNG HÔ:" in lead_profile_text(None)
    assert "anh/chị" in lead_profile_text(None)
    assert "'anh'" in lead_profile_text({"gender": "male"})
    assert "'chị'" in lead_profile_text({"gender": "female"})


def test_no_static_reply_is_empty():
    """An empty constant would silently send nothing — guard against it too."""
    for name, reply in STATIC_REPLIES.items():
        assert reply and reply.strip(), f"{name} is empty"


def test_persona_states_pronoun_contract_before_everything_else():
    """The voice rule must lead the persona, not sit buried in a bullet list.

    Live replies drifted to "Bạn có muốn…" while the ban existed as item 3 of a
    ten-item list. Position is the fix: the contract is checked first.
    """
    persona = AGENT_SYSTEM_PROMPT
    head = persona[: persona.index("### Giao tiếp")]

    assert "Giọng nói" in head, "voice contract must appear before the communication section"
    assert "BẮT BUỘC" in head, "the voice contract must be marked mandatory"
    for banned in ('"bạn"', '"mình"', '"tôi"'):
        assert banned in head, f"voice contract must name {banned} as forbidden"
    assert "anh/chị" in head


def test_persona_makes_phone_capture_the_objective():
    """Collecting the phone number is the mission, not a side effect."""
    persona = AGENT_SYSTEM_PROMPT

    assert "Nhiệm vụ chính" in persona
    assert "SĐT" in persona
    # The retired line told the model the system handled phone capture on its own
    # and that it should not push — the reason the bot rarely asked.
    assert "được hệ thống tự động" not in persona, (
        "persona must not tell the model that lead/phone capture is automatic"
    )


def test_persona_requires_denying_what_is_not_available():
    """Listing alternatives without denying the premise is an incomplete answer."""
    assert "TRẢ LỜI THẲNG khi không có" in AGENT_SYSTEM_PROMPT
