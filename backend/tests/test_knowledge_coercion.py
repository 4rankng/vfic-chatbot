"""Pure unit tests for the knowledge-pipeline coercion helpers.

No DB, no LLM, no asyncio — these lock the LLM-output coercion behavior so the Phase 1
clean-architecture refactor (splitting knowledge_pipeline.py into the services/knowledge/
package) cannot regress it. Sync functions by design (no asyncio mark).
"""
import json
from types import SimpleNamespace

import pytest

from app.services.knowledge.coercion import (
    DigestError,
    _clamp_strength,
    _coerce_feature,
    _coerce_unit,
    _missing_feature_text,
    _parse_json_lenient,
    _product_feature_prompt,
    validate_digest,
)


def _catalog(**kw):
    defaults = {
        "feature_key": "take_home_income",
        "name_vi": "Thu nhập",
        "worker_question_vi": "Thu nhập bao nhiêu?",
        "default_importance_score": 0.9,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# --------------------------------------------------------------------------- _coerce_unit
def test_coerce_unit_happy_preserves_fields():
    unit = _coerce_unit(
        {
            "content": "lương 10 triệu",
            "category": "salary",
            "confidence": "high",
            "questions": ["q1"],
            "entities": {"x": 1},
            "is_inference": True,
        }
    )
    assert unit["content"] == "lương 10 triệu"
    assert unit["category"] == "salary"
    assert unit["confidence"] == "high"
    assert unit["questions"] == ["q1"]
    assert unit["entities"] == {"x": 1}
    assert unit["is_inference"] is True


def test_coerce_unit_bad_category_falls_to_other():
    assert _coerce_unit({"content": "x", "category": "NOPE"})["category"] == "other"


def test_coerce_unit_bad_confidence_falls_to_medium():
    assert _coerce_unit({"content": "x", "confidence": "NOPE"})["confidence"] == "medium"


def test_coerce_unit_non_list_questions_coerced_to_list():
    assert _coerce_unit({"content": "x", "questions": "single"})["questions"] == ["single"]


def test_coerce_unit_rejects_non_dict():
    with pytest.raises(DigestError):
        _coerce_unit("not a dict")


def test_coerce_unit_rejects_empty_content():
    with pytest.raises(DigestError):
        _coerce_unit({"content": "   "})


# --------------------------------------------------------------------------- validate_digest
def test_validate_digest_string_payload_parses():
    summary, units = validate_digest(
        json.dumps({"document_summary": "tóm tắt", "units": [{"content": "c"}]})
    )
    assert summary == "tóm tắt"
    assert len(units) == 1


def test_validate_digest_non_dict_top_level_rejected():
    with pytest.raises(DigestError):
        validate_digest(42)


def test_validate_digest_missing_units_rejected():
    with pytest.raises(DigestError):
        validate_digest({"document_summary": "s"})


# --------------------------------------------------------------------------- _coerce_feature
def test_coerce_feature_non_dict_marks_missing():
    out = _coerce_feature(None, _catalog())
    assert out["is_missing"] is True
    assert out["is_highlight"] is False
    assert out["strength_score"] == 0.0
    assert "chưa ghi rõ" in out["value_text"]


def test_coerce_feature_missing_uses_template_text():
    out = _coerce_feature({"value_text": "", "is_missing": True}, _catalog())
    assert out["is_missing"] is True
    assert out["is_highlight"] is False  # highlight suppressed when missing
    assert "Thu nhập bao nhiêu?" in out["value_text"]


def test_coerce_feature_highlight_suppressed_when_missing():
    out = _coerce_feature({"value_text": "", "is_highlight": True, "is_missing": True}, _catalog())
    assert out["is_highlight"] is False


def test_coerce_feature_happy_preserves_value_json_and_highlight():
    out = _coerce_feature(
        {"value_text": "10 triệu", "value_json": {"min": 10}, "is_highlight": True, "strength_score": 0.9},
        _catalog(),
    )
    assert out["is_missing"] is False
    assert out["is_highlight"] is True
    assert out["value_json"] == {"min": 10}
    assert out["strength_score"] == 0.9


def test_coerce_feature_non_dict_value_json_becomes_empty_dict():
    out = _coerce_feature({"value_text": "x", "value_json": "not a dict"}, _catalog())
    assert out["value_json"] == {}


# --------------------------------------------------------------------------- _clamp_strength
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 0.5),  # TypeError -> default
        ("abc", 0.5),  # ValueError -> default
        (-0.5, 0.0),  # clamped low
        (1.5, 1.0),  # clamped high
        (0.123, 0.12),  # rounded to 2 decimals
        (0.8, 0.8),  # unchanged
    ],
)
def test_clamp_strength(value, expected):
    assert _clamp_strength(value) == expected


# --------------------------------------------------------------------------- _parse_json_lenient
def test_parse_json_lenient_plain():
    assert _parse_json_lenient('{"a": 1}') == {"a": 1}


def test_parse_json_lenient_fenced():
    assert _parse_json_lenient('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_lenient_empty_returns_empty_dict():
    assert _parse_json_lenient("") == {}


# --------------------------------------------------------------------------- prompt/text helpers
def test_missing_feature_text_prefers_worker_question():
    # Template is `Tin tuyển dụng chưa ghi rõ: <q>.` — q keeps its own trailing punctuation.
    assert _missing_feature_text(_catalog()) == "Tin tuyển dụng chưa ghi rõ: Thu nhập bao nhiêu?."


def test_missing_feature_text_falls_back_to_name_when_no_question():
    assert _missing_feature_text(_catalog(worker_question_vi="")) == "Tin tuyển dụng chưa ghi rõ: Thu nhập."


def test_product_feature_prompt_inlines_catalog_and_replaces_placeholder():
    prompt = _product_feature_prompt(
        [
            _catalog(),
            _catalog(feature_key="pay_frequency", name_vi="Kỳ lương", worker_question_vi=""),
        ]
    )
    assert "- take_home_income: Thu nhập" in prompt
    assert "câu hỏi ứng viên" in prompt  # question suffix rendered for the first row
    assert "- pay_frequency: Kỳ lương" in prompt  # no suffix when no question
    assert "{{FEATURES}}" not in prompt  # placeholder fully replaced
