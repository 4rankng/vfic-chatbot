"""Persona-voice invariant guard.

Every bot-visible static reply string must refer to the bot as **em** and
address the user as **anh/chị**, NEVER bạn/tôi/mình (persona.md). This is the
net that catches hand-authored drift on the constants (LLM output is already
bound via AGENT_SYSTEM_PROMPT).

Every one of these strings is emitted before any lead lookup, so the candidate's
gender is never known on these paths. They must therefore use the neutral
"anh/chị" — a bare "anh" or "chị" here would be a coin-flip guess at the user's
gender, which is exactly what the address-form plumbing exists to avoid.

Tokenization is Unicode-aware so "xem"/"gửi"/"chính"/"nhanh" never trip the
pronoun check — only a standalone pronoun token does.
"""

from __future__ import annotations

import pytest

from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.services.lead.normalizers import address_form, lead_profile_text


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
