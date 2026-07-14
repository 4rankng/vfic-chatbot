"""Tests for versioned publishing (Tech-Lead Directive §7, §9).

These tests cover the publishing logic (versioning, idempotency, retirement)
using mocked DB calls — full DB round-trip requires alembic upgrade head.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.extraction_contracts import (
    ExtractionEnvelope,
    FaqEnvelopeData,
    validate_contract,
)
from app.services.knowledge.publishing.publisher import (
    PublishingError,
    natural_key,
    publish_contract,
)


def _faq_envelope(question: str, answer: str) -> ExtractionEnvelope:
    return validate_contract(
        {
            "schema_version": "1.0",
            "scope": {"type": "global"},
            "validity": {"timezone": "Asia/Ho_Chi_Minh"},
            "data": {
                "entity_type": "faq",
                "canonical_question": question,
                "answer": answer,
                "language": "vi",
                "resolution_type": "static_answer",
            },
            "evidence": [],
            "warnings": [],
        }
    )


def test_natural_key_faq_uses_normalized_question():
    data = FaqEnvelopeData(canonical_question="Hồ sơ gì?", answer="A")
    nk = natural_key("faq", data, "global")
    assert nk == ("global", "hồ sơ gì?")


def test_natural_key_benefit_uses_name():
    data = MagicMock(name="Phụ cấp", category="ALLOWANCE")
    data.name = "Phụ cấp"
    nk = natural_key("benefit", data, "job_posting")
    assert nk == ("job_posting", "phụ cấp")


async def test_publish_faq_first_publish_version_1(monkeypatch):
    """First publish of a FAQ → version 1, status='published'."""
    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalars.return_value.first.return_value = None  # no existing
    db.execute = AsyncMock(return_value=fake_result)
    db.add = MagicMock()
    db.flush = AsyncMock()

    envelope = _faq_envelope("Hồ sơ gì?", "Bạn cần CCCD.")
    result = await publish_contract(db, envelope)
    assert result.entity_type == "faq"
    assert result.version == 1
    assert result.no_op is False


async def test_publish_faq_idempotent_when_content_equal(monkeypatch):
    """Same content republished → no_op=True."""
    existing = MagicMock()
    existing.version = 3
    existing.answer = "Bạn cần CCCD."
    existing.canonical_question = "Hồ sơ gì?"

    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalars.return_value.first.return_value = existing
    db.execute = AsyncMock(return_value=fake_result)

    envelope = _faq_envelope("Hồ sơ gì?", "Bạn cần CCCD.")
    result = await publish_contract(db, envelope)
    assert result.no_op is True
    assert result.version == 3  # unchanged


async def test_publish_faq_new_version_on_content_change(monkeypatch):
    """Different content → new version, prior retired."""
    existing = MagicMock()
    existing.version = 1
    existing.answer = "Old answer"
    existing.canonical_question = "Hồ sơ gì?"

    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalars.return_value.first.return_value = existing
    db.execute = AsyncMock(return_value=fake_result)
    db.add = MagicMock()
    db.flush = AsyncMock()

    envelope = _faq_envelope("Hồ sơ gì?", "New answer")
    result = await publish_contract(db, envelope)
    assert result.no_op is False
    assert result.version == 2  # bumped
    # Prior row retired
    assert existing.status == "retired"


async def test_publish_job_requirement_requires_job_id():
    """job_requirement publishing without job_id → PublishingError."""
    envelope = validate_contract(
        {
            "schema_version": "1.0",
            "scope": {"type": "job_posting", "id": "job-1"},
            "validity": {},
            "data": {
                "entity_type": "job_requirement",
                "text": "Nam 18-35 tuổi",
                "category": "age",
            },
            "evidence": [],
            "warnings": [],
        }
    )
    db = MagicMock()
    # job_id NOT provided
    with pytest.raises(PublishingError, match="job_id"):
        await publish_contract(db, envelope)


async def test_publish_unsupported_entity_type_raises():
    """An unsupported entity_type raises PublishingError."""
    # Build a valid FAQ envelope, then mutate entity_type to unsupported.
    envelope = _faq_envelope("Q", "A")
    # Bypass validation by patching the entity_type string
    object.__setattr__(envelope.data, "entity_type", "unknown_type")
    db = MagicMock()
    with pytest.raises(PublishingError, match="unsupported"):
        await publish_contract(db, envelope)
