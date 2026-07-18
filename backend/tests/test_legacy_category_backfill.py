from datetime import time

from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.knowledge.legacy_category_backfill import (
    LegacyCategorySnapshot,
    LegacyFaq,
    LegacyFeature,
    LegacyRoute,
    LegacyStop,
    build_legacy_category_documents,
)


def test_builds_supported_categories_from_existing_structured_facts() -> None:
    snapshot = LegacyCategorySnapshot(
        project_name="LG Display",
        project_aliases=("LGD",),
        job_titles=("Công nhân thời vụ",),
        job_evidence=(
            "LG Display tuyển công nhân thời vụ tại Khu công nghiệp Tràng Duệ, An Dương, Hải Phòng.",
        ),
        features=(
            LegacyFeature(
                key="salary_transparency",
                value_text="Lương cơ bản 6.030.000 VND/tháng.",
                value_json={
                    "base_salary": 6_030_000,
                    "total_without_ot": {"min": 7_430_000, "max": 7_930_000},
                    "allowances": [{"name": "Phụ cấp công việc", "amount": 500_000}],
                },
            ),
            LegacyFeature(
                key="shift_schedule",
                value_text="Ca ngày 08:00-20:00 hoặc ca đêm 20:00-08:00.",
            ),
            LegacyFeature(
                key="application_simplicity",
                value_text="CCCD và 2 ảnh 4x6; không thu phí.",
                value_json={
                    "age_requirement": "18-50 tuổi",
                    "health_requirement": "Sức khỏe ổn định",
                    "required_documents": ["CCCD", "2 ảnh 4x6"],
                    "cost_to_applicant": 0,
                },
            ),
            LegacyFeature(
                key="job_difficulty",
                value_text="Không yêu cầu kinh nghiệm; có đào tạo.",
                value_json={"education_required": False, "experience_required": False},
            ),
            LegacyFeature(key="housing", value_text="Có ký túc xá cho người ở xa."),
            LegacyFeature(
                key="daily_cost_benefits",
                value_text="Hỗ trợ xe và hồ sơ miễn phí.",
            ),
            LegacyFeature(
                key="contact_info",
                value_text="Liên hệ Admin Mai.",
                value_json={"training_day_contact": "Admin Mai - 0868232891"},
            ),
        ),
        routes=(
            LegacyRoute(
                source_id="00000000-0000-0000-0000-000000000001",
                route_key="ha-noi",
                name="Hà Nội",
                shift="admin",
                direction="outbound",
                stops=(
                    LegacyStop(1, "Keangnam", time(5, 25)),
                    LegacyStop(2, "Cầu Thanh Trì", time(6, 20)),
                ),
            ),
        ),
        faqs=(
            LegacyFaq("Có được tham gia BHXH không?", "Có, từ tháng làm việc thứ 2."),
            LegacyFaq("LG tuyển nam hay nữ?", "LG nhận cả nam và nữ."),
        ),
    )

    documents = build_legacy_category_documents(snapshot)

    assert KnowledgeCategoryKey.MEALS not in documents
    assert documents[KnowledgeCategoryKey.JOBS].jobs[0].title == "Công nhân thời vụ"
    assert documents[KnowledgeCategoryKey.JOBS].jobs[0].location == (
        "Khu công nghiệp Tràng Duệ, An Dương, Hải Phòng"
    )
    assert documents[KnowledgeCategoryKey.COMPENSATION].compensation[0].base_salary_vnd == 6_030_000
    assert documents[KnowledgeCategoryKey.REQUIREMENTS].requirements[0].age_min == 18
    assert documents[KnowledgeCategoryKey.REQUIREMENTS].requirements[0].genders == ["any"]
    assert len(documents[KnowledgeCategoryKey.TRANSPORTATION].transportation[0].stops) == 2
    assert (
        documents[KnowledgeCategoryKey.TRANSPORTATION].transportation[0].stops[0].time
        == "05:25"
    )
    assert documents[KnowledgeCategoryKey.INSURANCE].insurance[0].coverage == ["BHXH"]
    assert len(documents[KnowledgeCategoryKey.FAQ].faq) == 2


def test_faq_backfill_deduplicates_questions_and_keeps_longer_answer() -> None:
    snapshot = LegacyCategorySnapshot(
        project_name="Factory",
        project_aliases=(),
        job_titles=("Công nhân",),
        job_evidence=("Factory tuyển công nhân.",),
        features=(),
        routes=(),
        faqs=(
            LegacyFaq("Có xe không?", "Có."),
            LegacyFaq("  có xe không? ", "Có xe theo tuyến cố định."),
        ),
    )

    document = build_legacy_category_documents(snapshot)[KnowledgeCategoryKey.FAQ]

    assert len(document.faq) == 1
    assert document.faq[0].answer == "Có xe theo tuyến cố định."
