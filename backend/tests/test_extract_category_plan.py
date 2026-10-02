"""Complete, resumable, source-grounded extraction of arbitrary project text."""

from __future__ import annotations

import copy
import json
import unicodedata
from unittest.mock import AsyncMock

import pytest

from app.project_knowledge.domain.category_catalog import CATEGORY_DEFINITIONS
from app.services.knowledge.category_markdown import parse_category_markdown
from app.services.knowledge.extraction import (
    CATEGORY_PLAN_SECTION_CHARS,
    CATEGORY_PLAN_VERSION,
    CategoryPlanExtractionError,
    extract_category_plan,
)


def _response(**categories):
    data = {definition.key.value: [] for definition in CATEGORY_DEFINITIONS}
    data.update(categories)
    return json.dumps(data, ensure_ascii=False)


def _envelope(record, *quotes):
    return {"record": record, "source_quotes": list(quotes)}


_JOB_SOURCE = "Tuyển Nhân viên lắp ráp tại Hải Phòng. Lắp ráp linh kiện điện tử."
_JOB = _envelope(
    {
        "title": "Nhân viên lắp ráp",
        "location": "Hải Phòng",
        "summary": "Lắp ráp linh kiện điện tử.",
    },
    _JOB_SOURCE,
)
_CONTACT_SOURCE = "Liên hệ Cường, Cán bộ hồ sơ: 0859256588 tại KCN Vsip. Đón tiếp."
_CONTACT = _envelope(
    {
        "name": "Cường",
        "role": "Cán bộ hồ sơ",
        "phone": "0859256588",
        "zalo": "0859256588",
        "address": "KCN Vsip",
        "notes": "Đón tiếp.",
    },
    _CONTACT_SOURCE,
)


async def test_maps_unstructured_prose_into_valid_category_writes():
    source = _JOB_SOURCE + "\n\n" + _CONTACT_SOURCE
    llm = AsyncMock(return_value=_response(jobs=[_JOB], contacts=[_CONTACT]))
    plan = await extract_category_plan(source, llm)
    assert plan is not None
    assert [write.key.value for write in plan.writes] == ["jobs", "contacts"]
    jobs, contacts = plan.writes
    assert "### record: auto-jobs-" in jobs.content
    assert "0859256588" in contacts.content
    assert llm.await_args.args[1] == source
    prompt = llm.await_args.args[0]
    assert '"$defs"' in prompt and '"direction"' in prompt and '"round_trip"' in prompt
    assert '"amount_vnd"' in prompt and '"cadence"' in prompt and "source_quotes" in prompt


@pytest.mark.parametrize("payload", ["not json", "[]", "{}", '{"jobs": []}'])
async def test_invalid_extraction_fails_instead_of_plain_ingestion_fallback(payload):
    with pytest.raises(CategoryPlanExtractionError):
        await extract_category_plan(_JOB_SOURCE, AsyncMock(return_value=payload))


async def test_no_facts_and_empty_source_are_explicitly_empty():
    assert (
        await extract_category_plan("Thông báo nội bộ.", AsyncMock(return_value=_response()))
        is None
    )
    llm = AsyncMock()
    assert await extract_category_plan("  \n\t", llm) is None
    llm.assert_not_awaited()


async def test_provider_failure_is_safe_and_does_not_return_partial_success():
    with pytest.raises(CategoryPlanExtractionError) as error:
        await extract_category_plan(
            _JOB_SOURCE, AsyncMock(side_effect=RuntimeError("private provider payload"))
        )
    assert "private" not in str(error.value)


async def test_unverifiable_records_are_dropped_without_voiding_the_valid_ones():
    """One record with no usable evidence must not void the whole upload.

    The dropped category simply does not appear in the plan (the ingest summary
    lists it under "needs manual entry"), and the grounded record still trains.
    """
    llm = AsyncMock(return_value=_response(jobs=[_JOB], contacts=[{"nonsense": True}]))
    plan = await extract_category_plan(_JOB_SOURCE, llm)
    assert plan is not None
    assert [write.key.value for write in plan.writes] == ["jobs"]


@pytest.mark.parametrize(
    "record",
    [
        {"title": "Công nhân"},
        {"record": {"title": "Công nhân"}, "source_quotes": []},
        _envelope({"title": "Công nhân"}, "Không có chỗ ở."),
        _envelope({"title": "Công nhân"}, "Tuyển kỹ sư"),
    ],
)
async def test_records_require_matching_quotes_and_fact_values(record):
    with pytest.raises(CategoryPlanExtractionError):
        await extract_category_plan(
            "Tuyển kỹ sư.", AsyncMock(return_value=_response(jobs=[record]))
        )


async def test_quote_grounding_accepts_whitespace_and_unicode_equivalence():
    source = "Công ty tuyển\nNhân viên lắp ráp."
    quote = unicodedata.normalize("NFD", "Nhân viên lắp ráp")
    plan = await extract_category_plan(
        source, AsyncMock(return_value=_response(jobs=[_envelope({"title": quote}, quote)]))
    )
    assert plan is not None


@pytest.mark.parametrize(
    "record,quote",
    [
        ({"base_salary_vnd": 9000000}, "Lương cơ bản: 6,5 triệu đồng/tháng."),
        ({"base_salary_vnd": 65}, "Lương cơ bản: 6,5 triệu đồng/tháng."),
        ({"provided": False}, "Không phục vụ bữa sáng, cung cấp cơm ca trưa."),
        ({"provided": False}, "Công ty không có bữa ăn miễn phí."),
        ({"available": True}, "Không có KTX."),
    ],
)
async def test_records_with_no_supported_fact_fail_the_extraction(record, quote):
    """Every cleared value leaves the record empty: the mapping failed, not "no source"."""
    key = (
        "compensation"
        if "base_salary_vnd" in record
        else "meals"
        if "provided" in record
        else "accommodation"
    )
    with pytest.raises(CategoryPlanExtractionError):
        await extract_category_plan(
            quote, AsyncMock(return_value=_response(**{key: [_envelope(record, quote)]}))
        )


async def test_unsupported_field_is_cleared_while_the_grounded_fields_publish():
    """A fabricated value never publishes, and it no longer sinks its own record.

    The phone is not in the brief, so it is cleared; the quoted name survives.
    """
    record = _envelope({"name": "Cường", "phone": "0909999999"}, _CONTACT_SOURCE)
    plan = await extract_category_plan(
        _CONTACT_SOURCE, AsyncMock(return_value=_response(contacts=[record]))
    )
    assert plan is not None
    document = parse_category_markdown(plan.writes[0].key, plan.writes[0].content)
    contact = document.contacts[0]
    assert contact.name == "Cường"
    assert contact.phone is None


async def test_unsupported_list_item_is_dropped_and_its_siblings_kept():
    source = "## Câu hỏi thường gặp\n- **Có xe đưa đón không?**  Không có xe đưa đón.\n"
    record = _envelope(
        {
            "question": "Có xe đưa đón không?",
            "answer": "Không có xe đưa đón.",
            "tags": ["đưa đón", "miễn phí"],
        },
        "- **Có xe đưa đón không?**  Không có xe đưa đón.",
    )
    plan = await extract_category_plan(
        source, AsyncMock(return_value=_response(faq=[record]))
    )
    assert plan is not None
    document = parse_category_markdown(plan.writes[0].key, plan.writes[0].content)
    assert document.faq[0].tags == ["đưa đón"]


async def test_long_plain_text_extracts_facts_after_character_60000():
    source = _JOB_SOURCE + "\n" + "Thông báo nội bộ. " * 4000 + "\n" + _CONTACT_SOURCE
    calls = []

    async def llm(_system, section):
        calls.append(section)
        return _response(
            jobs=[_JOB] if _JOB_SOURCE in section else [],
            contacts=[_CONTACT] if _CONTACT_SOURCE in section else [],
        )

    plan = await extract_category_plan(source, llm)
    assert plan is not None
    assert [write.key.value for write in plan.writes] == ["jobs", "contacts"]
    assert any("0859256588" in section for section in calls)
    assert all(len(section) <= CATEGORY_PLAN_SECTION_CHARS for section in calls)
    assert len(calls) > 1


async def test_overlap_deduplicates_records_with_deterministic_ids():
    source = _JOB_SOURCE + "\n" + "Thông báo nội bộ. " * 1000 + "\n" + _JOB_SOURCE
    calls = 0

    async def llm(_system, section):
        nonlocal calls
        calls += 1
        record = copy.deepcopy(_JOB)
        record["record"]["id"] = f"random-provider-id-{calls}"
        return _response(jobs=[record] if _JOB_SOURCE in section else [])

    plan = await extract_category_plan(source, llm)
    assert plan is not None and calls > 1
    document = parse_category_markdown(plan.writes[0].key, plan.writes[0].content)
    assert len(document.jobs) == 1


async def test_conflicting_source_facts_are_preserved_in_separate_records():
    first, second = "Đợt 1: Lương cơ bản 6.500.000 đồng.", "Đợt 2: Lương cơ bản 7.000.000 đồng."
    plan = await extract_category_plan(
        first + "\n" + second,
        AsyncMock(
            return_value=_response(
                compensation=[
                    _envelope({"id": "same-model-id", "base_salary_vnd": 6500000}, first),
                    _envelope({"id": "same-model-id", "base_salary_vnd": 7000000}, second),
                ]
            )
        ),
    )
    assert plan is not None
    document = parse_category_markdown(plan.writes[0].key, plan.writes[0].content)
    assert [record.base_salary_vnd for record in document.compensation] == [6500000, 7000000]


async def test_resume_only_calls_unfinished_sections_and_revalidates_saved_evidence(monkeypatch):
    monkeypatch.setattr("app.services.knowledge.extraction.CATEGORY_PLAN_SECTION_CHARS", 140)
    source = _JOB_SOURCE + "\n" + "Thông báo nội bộ. " * 20 + "\n" + _CONTACT_SOURCE
    saved = []
    calls = 0

    async def persist(checkpoint):
        saved.append(checkpoint)

    async def unreliable(_system, section):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("provider outage")
        return _response(jobs=[_JOB] if _JOB_SOURCE in section else [])

    with pytest.raises(CategoryPlanExtractionError):
        await extract_category_plan(source, unreliable, on_checkpoint=persist)
    checkpoint = saved[-1]
    assert checkpoint["version"] == CATEGORY_PLAN_VERSION
    assert checkpoint["completed_sections"] == 1 and checkpoint["status"] == "PROCESSING"

    remaining_calls = []

    async def repaired(_system, section):
        remaining_calls.append(section)
        return _response(contacts=[_CONTACT] if _CONTACT_SOURCE in section else [])

    plan = await extract_category_plan(
        source, repaired, checkpoint=checkpoint, on_checkpoint=persist
    )
    assert plan is not None
    assert len(remaining_calls) == checkpoint["total_sections"] - 1
    final = saved[-1]
    assert final["completed_sections"] == final["total_sections"]
    assert final["status"] == "COMPLETED"
    assert final["covered_categories"] == ["jobs", "contacts"]
    no_calls = AsyncMock()
    replay = await extract_category_plan(source, no_calls, checkpoint=final)
    assert replay == plan
    no_calls.assert_not_awaited()


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "source_sha256",
        "total_sections",
        "completed_sections",
        "section_hash",
        "section_index",
        "evidence",
    ],
)
async def test_tampered_checkpoint_never_skips_extraction(mutation):
    saved = []

    async def persist(checkpoint):
        saved.append(checkpoint)

    await extract_category_plan(
        _JOB_SOURCE, AsyncMock(return_value=_response(jobs=[_JOB])), on_checkpoint=persist
    )
    checkpoint = copy.deepcopy(saved[-1])
    if mutation in {"version", "source_sha256"}:
        checkpoint[mutation] = "wrong"
    elif mutation in {"total_sections", "completed_sections"}:
        checkpoint[mutation] += 1
    elif mutation == "section_hash":
        checkpoint["sections"][0]["source_sha256"] = "wrong"
    elif mutation == "section_index":
        checkpoint["sections"][0]["index"] = 9
    else:
        checkpoint["sections"][0]["categories"]["jobs"][0]["source_quotes"] = ["fabricated quote"]
    llm = AsyncMock()
    with pytest.raises(CategoryPlanExtractionError):
        await extract_category_plan(_JOB_SOURCE, llm, checkpoint=checkpoint)
    llm.assert_not_awaited()


async def test_section_budget_is_an_explicit_failure_before_any_provider_call(monkeypatch):
    monkeypatch.setattr("app.services.knowledge.extraction.CATEGORY_PLAN_MAX_SECTIONS", 1)
    llm = AsyncMock()
    with pytest.raises(CategoryPlanExtractionError, match="giới hạn"):
        await extract_category_plan("Thông báo. " * 2000, llm)
    llm.assert_not_awaited()


async def test_plain_vietnamese_source_supports_all_twelve_nested_category_contracts():
    records = {
        "jobs": _JOB,
        "compensation": _envelope(
            {
                "base_salary_vnd": 6500000,
                "estimated_income_min_vnd": 8500000,
                "estimated_income_max_vnd": 10500000,
                "allowances": [{"name": "Chuyên cần", "amount_vnd": 50000, "cadence": "day"}],
            },
            "Lương cơ bản 6,5 triệu; thu nhập 8,5 – 10,5 triệu đồng/tháng. Chuyên cần: 50k/ngày.",
        ),
        "requirements": _envelope(
            {
                "age_min": 18,
                "age_max": 40,
                "genders": ["any"],
                "education": "THCS",
                "experience": "Không cần kinh nghiệm",
            },
            "Tuyển nam nữ 18–40 tuổi, THCS. Không cần kinh nghiệm.",
        ),
        "work_schedules": _envelope(
            {
                "shifts": [
                    {"name": "Ca ngày", "start_time": "08:00", "end_time": "17:00"},
                    {
                        "name": "Ca đêm",
                        "start_time": "21:00",
                        "end_time": "05:00",
                        "crosses_midnight": True,
                    },
                ]
            },
            "Ca ngày 08:00–17:00. Ca đêm 21:00–05:00.",
        ),
        "benefits": _envelope(
            {"name": "đào tạo", "description": "Công ty đào tạo từ đầu."}, "Công ty đào tạo từ đầu."
        ),
        "accommodation": _envelope(
            {"available": True, "type": "KTX", "monthly_cost_vnd": 300000},
            "Có KTX: 300.000 đồng/tháng.",
        ),
        "meals": _envelope(
            {
                "provided": True,
                "meals_per_shift": 1,
                "notes": "Cung cấp 1 suất ăn cơm ca miễn phí.",
            },
            "Cung cấp 1 suất ăn cơm ca miễn phí.",
        ),
        "transportation": _envelope(
            {
                "name": "xe đưa đón",
                "direction": "round_trip",
                "fee_vnd": 0,
                "stops": [
                    {"order": 1, "name": "Cầu Rào", "time": "06:20"},
                    {"order": 2, "name": "Bến xe Vĩnh Niệm", "time": "07:10"},
                ],
            },
            "Có xe đưa đón miễn phí: Cầu Rào 06:20, Bến xe Vĩnh Niệm 07:10.",
        ),
        "insurance": _envelope(
            {"name": "BHXH", "starts_after": "tháng thứ hai"}, "Đóng BHXH từ tháng thứ hai."
        ),
        "application": _envelope(
            {"required_documents": ["CCCD"], "interview_location": "Văn phòng tuyển dụng"},
            "Phỏng vấn tại Văn phòng tuyển dụng. Mang CCCD.",
        ),
        "contacts": _CONTACT,
        "faq": _envelope(
            {"question": "Hồ sơ cần gì?", "answer": "Mang CCCD."}, "Hồ sơ cần gì? Mang CCCD."
        ),
    }
    source = "\n".join(
        quote for envelope in records.values() for quote in envelope["source_quotes"]
    )
    plan = await extract_category_plan(
        source,
        AsyncMock(return_value=_response(**{key: [envelope] for key, envelope in records.items()})),
    )
    assert plan is not None and len(plan.writes) == 12
    for write in plan.writes:
        parse_category_markdown(write.key, write.content)
    assert "0859256588" in plan.writes[10].content
    assert "10500000" in plan.writes[1].content and "06:20" in plan.writes[7].content


async def test_explicit_english_facts_and_omitted_defaults_survive_checkpoint_replay():
    source = "Recruiting Assembly worker, male. Attendance: VND 500000 per month. Housing is available. Meals are provided."
    response = _response(
        jobs=[_envelope({"title": "Assembly worker"}, "Recruiting Assembly worker")],
        requirements=[_envelope({"genders": ["male"]}, "male")],
        compensation=[
            _envelope(
                {"allowances": [{"name": "Attendance", "amount_vnd": 500000, "cadence": "month"}]},
                "Attendance: VND 500000 per month.",
            )
        ],
        accommodation=[_envelope({"available": True}, "Housing is available.")],
        meals=[_envelope({"provided": True}, "Meals are provided.")],
    )
    saved = []

    async def persist(checkpoint):
        saved.append(checkpoint)

    original = await extract_category_plan(
        source, AsyncMock(return_value=response), on_checkpoint=persist
    )
    llm = AsyncMock()
    replay = await extract_category_plan(source, llm, checkpoint=saved[-1])
    assert original == replay and original is not None
    assert len(original.writes) == 5
    llm.assert_not_awaited()


@pytest.mark.parametrize(
    "key,record,quote",
    [
        ("meals", {"provided": False}, "No meals are provided."),
        ("accommodation", {"available": False}, "Housing is not available."),
        (
            "accommodation",
            {"available": False},
            unicodedata.normalize("NFD", "Không có ký túc xá."),
        ),
    ],
)
async def test_explicit_service_absence_can_be_retained(key, record, quote):
    plan = await extract_category_plan(
        quote, AsyncMock(return_value=_response(**{key: [_envelope(record, quote)]}))
    )
    assert plan is not None and plan.writes[0].key.value == key


async def test_gender_enum_male_is_not_grounded_by_female_substring():
    with pytest.raises(CategoryPlanExtractionError):
        await extract_category_plan(
            "Only female candidates.",
            AsyncMock(
                return_value=_response(
                    requirements=[_envelope({"genders": ["male"]}, "Only female candidates.")]
                )
            ),
        )


async def test_explicit_foreign_currency_is_not_published_as_vnd():
    with pytest.raises(CategoryPlanExtractionError):
        await extract_category_plan(
            "Base salary: USD 500 per month.",
            AsyncMock(
                return_value=_response(
                    compensation=[
                        _envelope({"base_salary_vnd": 500}, "Base salary: USD 500 per month.")
                    ]
                )
            ),
        )


async def test_duplicate_json_category_keys_are_rejected():
    response = _response(jobs=[_JOB])[:-1] + ', "jobs": []}'
    with pytest.raises(CategoryPlanExtractionError):
        await extract_category_plan(_JOB_SOURCE, AsyncMock(return_value=response))


@pytest.mark.parametrize(
    "quote,amount",
    [
        ("Lương cơ bản: 6tr5/tháng.", 6500000),
        ("Lương cơ bản: 6tr/tháng.", 6000000),
        ("Base salary: VND 6.5 million per month.", 6500000),
        ("Lương cơ bản: 6.500.000 đồng/tháng.", 6500000),
    ],
)
async def test_source_money_notation_normalizes_without_inventing_values(quote, amount):
    plan = await extract_category_plan(
        quote,
        AsyncMock(
            return_value=_response(compensation=[_envelope({"base_salary_vnd": amount}, quote)])
        ),
    )
    assert plan is not None and str(amount) in plan.writes[0].content


async def test_normalized_vietnamese_hour_notation_keeps_the_actual_bus_times():
    source = "Xe đưa đón: Cầu Rào 6h20, Bến xe Vĩnh Niệm 7 giờ 10."
    record = {
        "name": "Xe đưa đón",
        "direction": "round_trip",
        "stops": [
            {"order": 1, "name": "Cầu Rào", "time": "06:20"},
            {"order": 2, "name": "Bến xe Vĩnh Niệm", "time": "07:10"},
        ],
    }
    plan = await extract_category_plan(
        source, AsyncMock(return_value=_response(transportation=[_envelope(record, source)]))
    )
    assert (
        plan is not None and "06:20" in plan.writes[0].content and "07:10" in plan.writes[0].content
    )


async def test_pay_date_and_foreign_currency_do_not_ground_a_vnd_salary():
    source = "Lương cơ bản USD 500. Phụ cấp 300.000 đồng. Trả lương ngày 31."
    for fabricated in (500, 31):
        with pytest.raises(CategoryPlanExtractionError):
            await extract_category_plan(
                source,
                AsyncMock(
                    return_value=_response(
                        compensation=[_envelope({"base_salary_vnd": fabricated}, source)]
                    )
                ),
            )


@pytest.mark.parametrize(
    "key,record,quote",
    [
        ("accommodation", {"available": True}, "Có ký túc xá không?"),
        ("meals", {"provided": True}, "Thông tin cơm ca chưa rõ."),
    ],
)
async def test_questions_unknown_services_and_negated_free_are_not_positive_facts(
    key, record, quote
):
    with pytest.raises(CategoryPlanExtractionError):
        await extract_category_plan(
            quote, AsyncMock(return_value=_response(**{key: [_envelope(record, quote)]}))
        )


@pytest.mark.parametrize(
    "quote", ["Có KTX nhưng không miễn phí.", "Housing is available but not free."]
)
async def test_denied_free_price_clears_the_free_claim_but_keeps_availability(quote):
    """A cost invented from "not free" is cleared; the sourced availability stays."""
    record = _envelope({"available": True, "monthly_cost_vnd": 0}, quote)
    plan = await extract_category_plan(
        quote, AsyncMock(return_value=_response(accommodation=[record]))
    )
    assert plan is not None
    document = parse_category_markdown(plan.writes[0].key, plan.writes[0].content)
    assert document.accommodation[0].available is True
    assert document.accommodation[0].monthly_cost_vnd is None


async def test_quote_grounding_ignores_markdown_emphasis_and_bullets():
    """The provider cites a brief line's words, not the brief's markdown."""
    source = "# 4P Electronics\n\n- **Lương cơ bản:** 6.200.000 – 6.300.000 VNĐ / tháng.\n"
    record = _envelope(
        {"base_salary_vnd": 6200000}, "Lương cơ bản: 6.200.000 – 6.300.000 VNĐ / tháng."
    )
    plan = await extract_category_plan(
        source, AsyncMock(return_value=_response(compensation=[record]))
    )
    assert plan is not None
    assert [write.key.value for write in plan.writes] == ["compensation"]


async def test_composed_field_is_grounded_against_the_whole_section():
    """A field may rest on a line the record did not list in its own quotes.

    The provider routinely cites a subset of the lines a composed field draws on
    (here the FAQ answer restating the commute allowance), and a subset citation
    is not a fabrication.
    """
    source = (
        "## Đưa đón & lịch xe\n"
        "- **Phụ cấp đi lại:** Hỗ trợ 300.000 VNĐ / tháng tiền đi lại vào lương.\n"
        "## Câu hỏi thường gặp\n"
        "- **Có xe đưa đón không?**\n"
        "  Không có xe đưa đón. Công ty hỗ trợ 300.000 VNĐ/tháng tiền phụ cấp đi lại trực tiếp "
        "vào lương.\n"
    )
    record = _envelope(
        {
            "name": "Phụ cấp đi lại",
            "direction": "round_trip",
            "notes": (
                "Không có xe đưa đón. Công ty hỗ trợ 300.000 VNĐ/tháng tiền phụ cấp đi lại "
                "trực tiếp vào lương."
            ),
        },
        "- **Phụ cấp đi lại:** Hỗ trợ 300.000 VNĐ / tháng tiền đi lại vào lương.",
    )
    plan = await extract_category_plan(
        source, AsyncMock(return_value=_response(transportation=[record]))
    )
    assert plan is not None
    document = parse_category_markdown(plan.writes[0].key, plan.writes[0].content)
    assert document.transportation[0].notes.startswith("Không có xe đưa đón.")


@pytest.mark.parametrize(
    "key,record,quote",
    [
        (
            "meals",
            {"provided": True, "notes": "Bữa trưa miễn phí"},
            "Bữa ăn: có bữa trưa miễn phí.",
        ),
        ("accommodation", {"available": True}, "Chỗ ở: có ký túc xá nhưng không miễn phí."),
        ("accommodation", {"available": True}, "Có KTX không miễn phí."),
        ("accommodation", {"available": True}, "Housing is available, not free."),
    ],
)
async def test_affirmed_service_is_retained_when_only_free_price_is_denied(key, record, quote):
    plan = await extract_category_plan(
        quote, AsyncMock(return_value=_response(**{key: [_envelope(record, quote)]}))
    )
    assert plan is not None and plan.writes[0].key.value == key
