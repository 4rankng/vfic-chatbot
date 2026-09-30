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


def test_persona_states_the_pronoun_contract():
    """The address-form contract must survive the Studio's 7-part rewrite.

    It now lives in §6 ("Tôi nên giao tiếp với mọi người như thế nào?") as an
    absolute rule: bot = "em", user = "anh"/"chị"/"anh/chị", with the forbidden
    forms named explicitly so the model never emits "bạn"/"tôi"/"mình".
    """
    persona = AGENT_SYSTEM_PROMPT

    assert "Ngôi xưng tuyệt đối" in persona, "persona must state the address-form contract"
    assert "anh/chị" in persona
    for banned in ('"bạn"', '"mình"', '"tôi"'):
        assert banned in persona, f"address contract must name {banned} as forbidden"


def test_persona_makes_phone_capture_the_objective():
    """Collecting the phone number is the mission, not a side effect."""
    persona = AGENT_SYSTEM_PROMPT

    assert "MỤC TIÊU QUAN TRỌNG NHẤT" in persona
    assert "SỐ ĐIỆN THOẠI" in persona
    # The retired line told the model the system handled phone capture on its own
    # and that it should not push — the reason the bot rarely asked.
    assert "được hệ thống tự động" not in persona, (
        "persona must not tell the model that lead/phone capture is automatic"
    )
