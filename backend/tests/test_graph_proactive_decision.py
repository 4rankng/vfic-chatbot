"""Characterization tests for graph/proactive.py — the proactive-outreach decision.

The follow-up *cadence rules* are already covered by
``test_proactive_followup_rules.py``. What was untested (F-CRIT-2) is the
**outreach decision surface**: the LLM JSON-decision parser and the contextual
prompt builder that feeds it. Both are pure functions of their inputs, so they
are characterized here without an LLM / DB / Redis.

These pin the parser's leniency (markdown fences, prose around JSON, malformed
input) and the context builder's history filtering (suppressed messages dropped,
speaker labels, the JSON-instruction contract).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.graph.proactive import (
    _build_proactive_user_text,
    parse_proactive_decision,
)
from app.models.conversation import DeliveryStatus, MessageSender


# ---------------------------------------------------------------------------
# parse_proactive_decision
# ---------------------------------------------------------------------------


def test_parse_decision_clean_json():
    d = parse_proactive_decision(
        '{"send": true, "message": "Chào anh, còn tìm việc không?", "reason": "warm lead"}'
    )
    assert d == {"send": True, "message": "Chào anh, còn tìm việc không?", "reason": "warm lead"}


def test_parse_decision_dict_input_is_jsonified():
    d = parse_proactive_decision({"send": False, "message": "", "reason": "cold"})
    assert d["send"] is False
    assert d["reason"] == "cold"


def test_parse_decision_strips_json_fences():
    d = parse_proactive_decision('```json\n{"send": true, "message": "hi"}\n```')
    assert d["send"] is True
    assert d["message"] == "hi"


def test_parse_decision_extracts_json_embedded_in_prose():
    d = parse_proactive_decision(
        'Sure! Here is the decision: {"send": true, "message": "go", "reason": "x"} hope that helps'
    )
    assert d["send"] is True
    assert d["message"] == "go"


def test_parse_decision_invalid_returns_safe_default():
    d = parse_proactive_decision("the candidate is not interested")
    assert d == {"send": False, "message": "", "reason": "invalid_decision_json"}


def test_parse_decision_missing_send_defaults_false():
    # an LLM that omits the "send" key must be treated as "do not send"
    d = parse_proactive_decision('{"message": "hi", "reason": "x"}')
    assert d["send"] is False


def test_parse_decision_strips_whitespace_in_message_and_reason():
    d = parse_proactive_decision(
        '{"send": true, "message": "  goto work  ", "reason": "   warm   "}'
    )
    assert d["message"] == "goto work"
    assert d["reason"] == "warm"


# ---------------------------------------------------------------------------
# _build_proactive_user_text
# ---------------------------------------------------------------------------


def _msg(body, sender, status=DeliveryStatus.DELIVERED):
    return SimpleNamespace(body=body, sender=sender, delivery_status=status)


def test_proactive_text_includes_chat_id_and_instruction():
    text = _build_proactive_user_text(chat_id="zalo-123", recent_messages=[], lead_profile="")
    assert "CHAT_ID: zalo-123" in text
    # the single-call JSON decision contract is always present
    assert '"send": true' in text
    assert "reason" in text


def test_proactive_text_labels_history_by_speaker():
    history = [
        _msg("Xin hỏi còn tuyển tài xế không?", MessageSender.WORKER),
        _msg("Dạ có anh ạ", MessageSender.BOT),
        _msg("Anh gửi hồ sơ nhé", MessageSender.RECRUITER),
    ]
    text = _build_proactive_user_text(chat_id="c1", recent_messages=history)
    assert "- Ứng viên: Xin hỏi còn tuyển tài xế không?" in text
    assert "- Bot: Dạ có anh ạ" in text
    assert "- Nhân viên: Anh gửi hồ sơ nhé" in text


def test_proactive_text_drops_suppressed_messages():
    history = [
        _msg("visible", MessageSender.WORKER, DeliveryStatus.DELIVERED),
        _msg("secret-unsent", MessageSender.BOT, DeliveryStatus.SUPPRESSED),
    ]
    text = _build_proactive_user_text(chat_id="c1", recent_messages=history)
    assert "visible" in text
    assert "secret-unsent" not in text


def test_proactive_text_empty_history_placeholder():
    text = _build_proactive_user_text(chat_id="c1", recent_messages=[], lead_profile="")
    assert "(chưa có tin nhắn trước đó)" in text


def test_proactive_text_includes_lead_profile_when_given():
    text = _build_proactive_user_text(
        chat_id="c1", recent_messages=[], lead_profile="Hồ sơ: tài xế, 5 năm KN"
    )
    assert "Hồ sơ: tài xế, 5 năm KN" in text
