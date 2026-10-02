"""Complete bounded automatic feature extraction, grounding and durable resume."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.knowledge.extraction import CATEGORY_PLAN_SECTION_CHARS, category_plan_sections
from app.services.knowledge.pipeline import KnowledgePipeline


def _catalog():
    return SimpleNamespace(
        id=uuid.uuid4(), feature_key="take_home_income", name_vi="Thu nhập",
        worker_question_vi="Thu nhập bao nhiêu?",
    )


def _fact(value, evidence, **changes):
    return {
        "feature_key": "take_home_income", "value_text": value,
        "value_json": {}, "evidence_text": evidence, "is_missing": False,
        "is_highlight": True, "needs_clarification": False, "strength_score": 0.8,
        **changes,
    }


def _pipeline(source, llm, *, auto=True, training=True):
    catalog = _catalog()
    metadata = {"project_training": {
        "auto_extract": auto, "processing_token": str(uuid.uuid4()),
    }} if training else {}
    doc = SimpleNamespace(
        id=uuid.uuid4(), project_id=uuid.uuid4(), raw_text=source,
        metadata_=metadata, digest_meta={},
    )
    pipeline = KnowledgePipeline(SimpleNamespace(commit=AsyncMock()), AsyncMock(), llm)
    pipeline.features = SimpleNamespace(fetch_catalog=AsyncMock(return_value=[catalog]), merge_for_project=AsyncMock())
    pipeline.index = SimpleNamespace(sync_highlights=AsyncMock())
    pipeline._guard_training = AsyncMock()
    return pipeline, doc


def _value(doc):
    return doc.metadata_["project_training"]["feature_values"][0]["value"]


async def test_auto_feature_calls_are_bounded_and_retain_fact_after_character_60000():
    tail = "Thu nhập 9 triệu đồng."
    source = "Ghi chú nguồn chưa có số tiền.\n" * 2600 + tail
    calls = []

    async def bounded_provider(_system, section):
        calls.append(section)
        if len(section) > CATEGORY_PLAN_SECTION_CHARS:
            raise RuntimeError("provider input exceeds its accepted source section")
        return json.dumps({"features": [_fact("9 triệu đồng", tail)] if tail in section else []})

    pipeline, doc = _pipeline(source, bounded_provider)
    await pipeline.extract_product_features(doc, [])
    assert len(source) > 60_000
    assert len(calls) == len(category_plan_sections(source)) > 1
    assert all(len(section) <= CATEGORY_PLAN_SECTION_CHARS for section in calls)
    assert calls[-1].endswith(tail)
    assert _value(doc)["value_text"] == "9 triệu đồng"
    assert not _value(doc)["is_missing"]
    assert doc.metadata_["project_training"]["feature_extraction"]["status"] == "COMPLETED"
    pipeline.features.merge_for_project.assert_not_called()


async def test_missing_later_sections_do_not_erase_an_earlier_concrete_feature():
    fact = "Thu nhập 6 triệu đồng."
    source = fact + "\n" + "Ghi chú chưa có tiền.\n" * 1600

    async def llm(_system, section):
        features = [_fact("6 triệu đồng", fact)] if fact in section else [_fact("", "", is_missing=True)]
        return json.dumps({"features": features})

    pipeline, doc = _pipeline(source, llm)
    await pipeline.extract_product_features(doc, [])
    assert _value(doc)["value_text"] == "6 triệu đồng"
    assert not _value(doc)["needs_clarification"]


@pytest.mark.parametrize("same_section", [False, True])
async def test_conflicting_facts_preserve_both_values_and_evidence_for_clarification(same_section):
    first, second = "Thu nhập 6 triệu đồng.", "Thu nhập 9 triệu đồng."
    source = first + "\n" + ("Ghi chú.\n" * 1600 if not same_section else "") + second

    async def llm(_system, section):
        features = []
        for evidence, value in ((first, "6 triệu đồng"), (second, "9 triệu đồng")):
            if evidence in section:
                features.append(_fact(value, evidence))
        return json.dumps({"features": features})

    pipeline, doc = _pipeline(source, llm)
    await pipeline.extract_product_features(doc, [])
    value = _value(doc)
    assert value["needs_clarification"] and not value["is_missing"]
    assert not value["is_highlight"]
    assert {item["value_text"] for item in value["value_json"]["extracted_variants"]} == {"6 triệu đồng", "9 triệu đồng"}
    assert first in value["evidence_text"] and second in value["evidence_text"]


async def test_feature_evidence_must_be_in_the_exact_provider_section():
    tail = "Thu nhập 9 triệu đồng."
    source = "Nội dung trước.\n" * 1800 + tail
    llm = AsyncMock(return_value=json.dumps({"features": [_fact("9 triệu đồng", tail)]}))
    pipeline, doc = _pipeline(source, llm)
    with pytest.raises(ValueError, match="source section"):
        await pipeline.extract_product_features(doc, [])
    assert tail not in llm.call_args.args[1]
    assert doc.metadata_["project_training"]["feature_extraction"]["completed_sections"] == 0
    assert "feature_values" not in doc.metadata_["project_training"]


async def test_provider_failure_keeps_completed_section_then_retry_skips_it():
    first, tail = "Thu nhập 6 triệu đồng.", "Thông tin cuối nguồn."
    source = first + "\n" + "Ghi chú.\n" * 2000 + tail
    calls = []

    async def interrupted(_system, section):
        calls.append(section)
        if len(calls) == 2:
            raise RuntimeError("provider unavailable")
        return json.dumps({"features": [_fact("6 triệu đồng", first)]})

    pipeline, doc = _pipeline(source, interrupted)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await pipeline.extract_product_features(doc, [])
    checkpoint = doc.metadata_["project_training"]["feature_extraction"]
    assert checkpoint["completed_sections"] == 1
    assert "feature_values" not in doc.metadata_["project_training"]
    retry_calls = []

    async def resume(_system, section):
        retry_calls.append(section)
        return json.dumps({"features": []})

    pipeline.llm_json = resume
    await pipeline.extract_product_features(doc, [])
    assert retry_calls == category_plan_sections(source)[1:]
    assert _value(doc)["value_text"] == "6 triệu đồng"
    # A later category failure can replay a fully completed feature extraction.
    pipeline.llm_json = AsyncMock(side_effect=AssertionError("completed sections must not repeat"))
    await pipeline.extract_product_features(doc, [])
    pipeline.llm_json.assert_not_called()


async def test_checkpoint_source_or_saved_section_tampering_cannot_be_reused():
    fact = "Thu nhập 6 triệu đồng."
    pipeline, doc = _pipeline(fact, AsyncMock(return_value=json.dumps({"features": [_fact("6 triệu đồng", fact)]})))
    await pipeline.extract_product_features(doc, [])
    doc.metadata_["project_training"]["feature_extraction"]["sections"][0]["source_sha256"] = "changed"
    pipeline.llm_json = AsyncMock()
    with pytest.raises(ValueError, match="section identity"):
        await pipeline.extract_product_features(doc, [])
    pipeline.llm_json.assert_not_called()
    doc.raw_text += " Nguồn bị đổi."
    with pytest.raises(ValueError, match="retained source"):
        await pipeline.extract_product_features(doc, [])


async def test_missing_only_source_prepares_missing_rows_without_publishing_over_old_values():
    source = "Nguồn chưa có thu nhập.\n" * 1000
    pipeline, doc = _pipeline(source, AsyncMock(return_value=json.dumps({"features": []})))
    await pipeline.extract_product_features(doc, [])
    assert _value(doc)["is_missing"]
    assert not _value(doc)["needs_clarification"]
    assert not _value(doc)["is_highlight"]
    pipeline.features.merge_for_project.assert_not_called()
    assert doc.digest_meta["features"]["status"] == "PREPARED"


@pytest.mark.parametrize("training", [False, True])
async def test_explicit_plan_and_nontraining_keep_existing_single_call_contract(training):
    source = "Thu nhập 6 triệu đồng.\n" * 1000
    llm = AsyncMock(return_value=json.dumps({"features": [_fact("6 triệu đồng", "Thu nhập 6 triệu đồng.")]}))
    pipeline, doc = _pipeline(source, llm, auto=False, training=training)
    await pipeline.extract_product_features(doc, [])
    llm.assert_awaited_once()
    assert llm.call_args.args[1] == source.strip()
    if training:
        assert "feature_extraction" not in doc.metadata_["project_training"]
    else:
        pipeline.features.merge_for_project.assert_awaited_once()
