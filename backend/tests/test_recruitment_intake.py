"""Candidate-provided contact evidence and phone-only readiness regressions."""

from unittest.mock import AsyncMock

import pytest

from app.recruitment.domain.intake import (
    candidate_contact_mobile,
    candidate_mobile,
    candidate_wish,
    has_full_name,
)
from app.services.candidate_extraction import CandidateExtractionService
from app.services.lead.normalizers import extract_self_reported_name, normalize_phone
from app.services.lead.probing import lead_collection_instruction, lead_collection_question


@pytest.mark.parametrize("value", ["0987654321", "+84 987 654 321", "84 987 654 321", "SĐT: 098.765.4321"])
def test_mobile_uses_complete_candidate_number(value):
    assert candidate_mobile(value) == "0987654321"


@pytest.mark.parametrize("value", [
    "02412345678", "0123456789", "09876543210", "0987abc654321",
    "0987654321 và 0912345678", "sinh năm 1995, mã 0987 654", "1800 7228",
])
def test_invalid_or_ambiguous_contact_does_not_count_as_mobile(value):
    assert candidate_mobile(value) is None


def test_phone_normalization_never_concatenates_distinct_numbers():
    assert normalize_phone("0987654321 / 0912345678") is None
    assert normalize_phone("0987abc654321") is None
    assert normalize_phone("02412345678") == "02412345678"  # Legacy landline contract.


@pytest.mark.parametrize("text", [
    "Hotline không gọi được, số của em là 0987654321",
    "Số của em là 098.765.4321, hotline không liên hệ được",
    "Số của mẹ em không dùng nữa; số điện thoại của em là +84 987 654 321",
    "0987654321 là số của em. Hotline không gọi được",
    "Hotline không gọi được nên số của em là 0987654321",
])
def test_explicit_candidate_mobile_is_scoped_to_its_ownership(text):
    assert candidate_contact_mobile(text) == "0987654321"
    assert lead_collection_question(lead=None, current_user_text=text, recent_messages=[]) == ""


@pytest.mark.parametrize("text", [
    "Số của em chưa có, hotline 0987654321",
    "Hotline không gọi được, gọi 0987654321 nhé",
    "Số của em là hotline 0987654321",
    "Số điện thoại công ty 0987654321, số của em là 0987654321",
    "Hotline 0912345678, số của em là 0987654321",
    "Số của em là 0987654321 là số của mẹ em",
])
def test_third_party_or_ambiguous_mobile_keeps_ownership_guard(text):
    assert candidate_contact_mobile(text) is None
    assert lead_collection_question(lead=None, current_user_text=text, recent_messages=[])


def test_compact_contact_reply_preserves_full_candidate_name():
    assert extract_self_reported_name("Nguyễn Văn An, 0987654321") == "Nguyễn Văn An"
    assert extract_self_reported_name("Em họ tên là Nguyễn Văn An, SĐT 0987654321") == "Nguyễn Văn An"
    assert extract_self_reported_name("Nguyễn Trãi") is None  # Could be a location.
    assert extract_self_reported_name("Lương bao nhiêu?", prev_bot_message="Cho em xin họ tên đầy đủ") is None
    assert extract_self_reported_name("Nguyễn Văn An", prev_bot_message="Anh/chị cho em xin họ tên đầy đủ nhé?") == "Nguyễn Văn An"


def test_names_are_recommended_information_never_fabricated():
    assert has_full_name("Nguyễn Văn An")
    assert not has_full_name("An")
    assert not has_full_name("0987654321")
    assert "bắt buộc duy nhất" in lead_collection_instruction(question="phone")
    assert "năm sinh tùy chọn" in lead_collection_instruction(question="phone")


@pytest.mark.parametrize("text", ["Rorze có xe không?", "tôi không muốn ứng tuyển Rorze", "tìm việc", "muốn làm gì?"])
def test_project_questions_and_refusals_are_not_application_wishes(text):
    assert candidate_wish(text) is None


def test_explicit_wish_preserves_project_and_candidate_words():
    assert candidate_wish("Em muốn ứng tuyển dự án Rorze, SĐT 0987654321") == "muốn ứng tuyển dự án Rorze"
    assert candidate_wish("Em muốn làm ca ngày ở Hải Phòng") == "muốn làm ca ngày ở Hải Phòng"


async def test_explicit_contact_survives_invalid_extractor_json():
    result = await CandidateExtractionService.extract(
        AsyncMock(return_value="not JSON"),
        "Em tên Nguyễn Văn An, 0987654321; em muốn ứng tuyển Rorze",
        "", "chat-1",
    )
    assert result.lead_patch is not None
    assert result.lead_patch["name"] == "Nguyễn Văn An"
    assert result.lead_patch["phone"] == "0987654321"
    assert result.lead_patch["desired_job"] == "muốn ứng tuyển Rorze"
    assert result.lead_patch["birth_year"] is None


async def test_explicit_mobile_survives_provider_failure_without_scoring_intent():
    result = await CandidateExtractionService.extract(
        AsyncMock(side_effect=RuntimeError("provider unavailable")),
        "SĐT của em 0987654321", "", "chat-1",
    )
    assert result.lead_patch is not None
    assert result.lead_patch["phone"] == "0987654321"
    assert result.lead_patch["lead_score"] is None
    assert result.lead_patch["name"] is None
    assert result.memory_facts == []


@pytest.mark.parametrize("text", [
    "Hotline không gọi được, số của em là 0987654321",
    "Số của mẹ em không dùng nữa; số của em là 0987654321",
])
@pytest.mark.parametrize("provider_result", [
    "not JSON",
    '{"lead_patch":{"phone":"0987654321"},"memory_facts":[]}',
    RuntimeError("provider unavailable"),
])
async def test_mixed_contact_context_survives_extraction_and_provider_fallback(text, provider_result):
    extractor = (
        AsyncMock(side_effect=provider_result)
        if isinstance(provider_result, Exception)
        else AsyncMock(return_value=provider_result)
    )
    result = await CandidateExtractionService.extract(extractor, text, "", "chat-1")
    assert result.lead_patch is not None
    assert result.lead_patch["phone"] == "0987654321"
    assert result.lead_patch["lead_score"] is None


async def test_model_invented_phone_is_not_saved_from_project_advice():
    result = await CandidateExtractionService.extract(
        AsyncMock(return_value='{"lead_patch":{"phone":"0987654321"},"memory_facts":[]}'),
        "Rorze có phụ cấp không?", "Gọi 0987654321", "chat-1",
    )
    assert result.lead_patch is not None
    assert result.lead_patch["phone"] is None


@pytest.mark.parametrize("text", [
    "Hotline 0987654321 phải không?",
    "Số điện thoại công ty 0987654321 đúng không?",
    "Số của mẹ em 0987654321",
])
async def test_quoted_third_party_phone_is_not_saved_as_candidate_contact(text):
    result = await CandidateExtractionService.extract(
        AsyncMock(return_value='{"lead_patch":{"phone":"0987654321"},"memory_facts":[]}'),
        text, "", "chat-1",
    )
    assert result.lead_patch is not None
    assert result.lead_patch["phone"] is None


async def test_non_contact_provider_failure_remains_visible():
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await CandidateExtractionService.extract(
            AsyncMock(side_effect=RuntimeError("provider unavailable")),
            "Rorze có xe không?", "", "chat-1",
        )
