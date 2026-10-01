"""Deterministic validation helpers for project-owned RAG category documents.

The job-reference rule has two halves that belong together: the pure check
(:func:`validate_job_references`) and the project-scoped lookup of which job ids
the *sibling* active revisions currently publish (:func:`validate_active_job_references`).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeCategory, KnowledgeCategoryRevision
from app.schemas.knowledge_categories import (
    CATEGORY_DOCUMENT_MODELS,
    JobsDocument,
    MAX_CATEGORY_RECORDS,
    CategoryDocument,
    KnowledgeCategoryKey,
)
from app.project_knowledge.domain.category import (
    category_payload_checksum,
    category_record_limit_exceeded,
    category_replacement_is_empty,
    unknown_job_references,
)
from app.services.knowledge.text_ingestion import normalize_kb_value


_TEMPLATE_DIR = Path(__file__).with_name("templates") / "categories"


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    key: KnowledgeCategoryKey
    label_vi: str
    list_field: str
    template_filename: str
    # The questions candidates actually ask about this category (mirrors the
    # operator's BIỂU MẪU THU THẬP collection form). Rendered into the combined
    # KB template so a recruiter knows what each category must answer.
    leading_questions: tuple[str, ...] = ()


CATEGORY_DEFINITIONS: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(
        KnowledgeCategoryKey.JOBS,
        "Vị trí tuyển dụng",
        "jobs",
        "jobs.md",
        (
            "Dự án đang tuyển công việc gì?",
            "Lương cơ bản bao nhiêu?",
            "1 tháng thực nhận về tay bao nhiêu?",
            "Có những khoản phụ cấp nào?",
            "Có thưởng đi làm không?",
            "Tăng ca tính thế nào?",
            "Bao giờ trả lương, theo tuần hay theo tháng?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.COMPENSATION,
        "Lương & thu nhập",
        "compensation",
        "compensation.md",
        (
            "Lương cơ bản bao nhiêu VNĐ?",
            "Thu nhập thực nhận thấp nhất và cao nhất là bao nhiêu?",
            "Có những khoản phụ cấp nào, mỗi khoản bao nhiêu?",
            "Có thưởng nào không (năng suất, thưởng nóng, thâm niên)?",
            "Tăng ca tính tiền như thế nào?",
            "Trả lương theo tuần hay theo tháng, chốt công ngày nào?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.REQUIREMENTS,
        "Yêu cầu ứng viên",
        "requirements",
        "requirements.md",
        (
            "Tuyển độ tuổi từ bao nhiêu đến bao nhiêu?",
            "Có yêu cầu bằng cấp không?",
            "Có cần kinh nghiệm hay được đào tạo từ đầu?",
            "Có nhận người có hình xăm không?",
            "Yêu cầu sức khỏe và giấy tờ gì (CCCD, hồ sơ)?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.WORK_SCHEDULES,
        "Ca làm việc",
        "work_schedules",
        "work_schedules.md",
        (
            "Làm mấy giờ đến mấy giờ?",
            "Có phải làm ca đêm không?",
            "Làm kíp luân phiên thế nào (mấy ngày ngày, mấy ngày đêm)?",
            "Một tháng được nghỉ mấy ngày, làm bao nhiêu công?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.BENEFITS,
        "Phúc lợi",
        "benefits",
        "benefits.md",
        (
            "Có thưởng nóng hoặc thưởng đi làm không, bao nhiêu?",
            "Có du lịch hay đào tạo gì không?",
            "Phúc lợi nổi bật nào thu hút ứng viên?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.ACCOMMODATION,
        "Chỗ ở",
        "accommodation",
        "accommodation.md",
        (
            "Công ty có ký túc xá không?",
            "Điều kiện để ở ký túc xá là gì?",
            "Không ở KTX có được hỗ trợ tìm phòng trọ không?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.MEALS,
        "Bữa ăn",
        "meals",
        "meals.md",
        (
            "Đi làm có được bao ăn không, mấy bữa?",
            "Cơm ca có mất tiền không?",
            "Không ăn ca có được hỗ trợ tiền không?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.TRANSPORTATION,
        "Đưa đón & lịch xe",
        "transportation",
        "transportation.md",
        (
            "Có xe đưa đón không?",
            "Đón ở những tỉnh, huyện nào?",
            "Điểm đón ở đâu, xe đón mấy giờ?",
            "Đi xe đưa đón có mất tiền không?",
            "Tự đi xe máy có được hỗ trợ tiền xăng không?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.INSURANCE,
        "Bảo hiểm",
        "insurance",
        "insurance.md",
        (
            "Có đóng BHXH không, từ khi nào?",
            "Khám sức khỏe đầu vào thế nào?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.APPLICATION,
        "Ứng tuyển & nhận việc",
        "application",
        "application.md",
        (
            "Phỏng vấn có khó không, có phải thi test không?",
            "Phỏng vấn mang theo giấy tờ gì, mặc gì?",
            "Hồ sơ đi làm cần những gì, công ty có hỗ trợ làm hồ sơ không?",
            "Phỏng vấn xong bao lâu thì được đi làm?",
            "Nghỉ việc trả đồng phục và thẻ ở đâu, báo trước mấy ngày?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.CONTACTS,
        "Liên hệ",
        "contacts",
        "contacts.md",
        (
            "Đến đào tạo hoặc nhận việc thì liên hệ ai, số nào?",
            "Nghỉ việc trả thẻ liên hệ ai?",
            "Địa chỉ văn phòng công ty ở đâu?",
            "Số Zalo của cán bộ phụ trách dự án là gì?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.FAQ,
        "Câu hỏi thường gặp",
        "faq",
        "faq.md",
        (
            "Tổng hợp các câu hỏi ứng viên hay gặp nhất theo từng giai đoạn:",
            "trước phỏng vấn, khi nhận việc, khi nghỉ việc.",
        ),
    ),
)

_DEFINITIONS_BY_KEY = {definition.key: definition for definition in CATEGORY_DEFINITIONS}


class EmptyCategoryError(ValueError):
    """Raised when replacement content has no rows and clear was not requested."""


class UnknownJobReferenceError(ValueError):
    """Raised when a category references a job absent from the current Jobs category."""


class CategoryMarkdownError(ValueError):
    """Raised when category content is not one well-formed Category Markdown v1 document."""


def get_category_definition(key: KnowledgeCategoryKey | str) -> CategoryDefinition:
    return _DEFINITIONS_BY_KEY[KnowledgeCategoryKey(key)]


def load_category_template(key: KnowledgeCategoryKey | str) -> str:
    definition = get_category_definition(key)
    return (_TEMPLATE_DIR / definition.template_filename).read_text(encoding="utf-8")


_FULL_TEMPLATE_FILENAME = "mau-kb-du-an.md"


def build_project_knowledge_template() -> str:
    """Render ONE operator-facing document covering every category.

    The per-category templates are correct but invisible: a recruiter who gets
    only ``jobs.md`` has no way to know the other eleven categories exist, let
    alone what each one must answer. This bundles every template in canonical
    order, each preceded by the questions candidates actually ask, so filling
    the answers produces a complete KB in a single upload.
    """
    parts = [
        "# MẪU XÂY DỰNG KIẾN THỨC DỰ ÁN (KB) — điền câu trả lời rồi tải tệp này lên",
        "",
        "Mỗi mục dưới đây là MỘT danh mục dữ liệu của dự án. Cách làm:",
        "1. Điền câu trả lời của dự án vào các chỗ [?] trong khối YAML của mục đó.",
        "2. GIỮ NGUYÊN dòng frontmatter (schema_version / category) và tiêu đề '## <danh mục>'.",
        "3. Xóa danh mục không dùng được ngay (thiếu dữ liệu) — đừng để khối trống.",
        "4. Tải tệp này lên phần Kiến thức của dự án để hệ thống tự cập nhật.",
        "",
        "Khối chú thích đầu mỗi mục là CÂU HỎI ỨNG VIÊN THƯỜNG HỎI — trả lời hết",
        "những câu đó là KB đủ cho tư vấn tự động.",
    ]
    for definition in CATEGORY_DEFINITIONS:
        questions = "\n".join(
            f"-- {question}" for question in definition.leading_questions
        )
        parts.append(
            f"\n<!-- ============================================================\n"
            f"DANH MỤC: {definition.label_vi} ({definition.key})\n"
            f"CÂU HỎI ỨNG VIÊN THƯỜNG HỎI — trả lời các câu này trong khối bên dưới:\n"
            f"{questions}\n"
            f"============================================================ -->\n"
            f"{load_category_template(definition.key)}"
        )
    return "\n\n".join(parts) + "\n"


def validate_category_payload(
    key: KnowledgeCategoryKey | str,
    payload: dict[str, Any],
    *,
    allow_empty: bool = False,
) -> CategoryDocument:
    category_key = KnowledgeCategoryKey(key)
    definition = get_category_definition(category_key)
    records = payload.get(definition.list_field)
    if isinstance(records, list) and category_record_limit_exceeded(
        len(records), MAX_CATEGORY_RECORDS
    ):
        raise CategoryMarkdownError(
            f"category exceeds the {MAX_CATEGORY_RECORDS:,} record limit"
        )
    normalized_payload = normalize_kb_value(payload)
    document = CATEGORY_DOCUMENT_MODELS[category_key].model_validate(normalized_payload)
    if not allow_empty and category_replacement_is_empty(
        len(getattr(document, definition.list_field))
    ):
        raise EmptyCategoryError(
            "category replacement must contain at least one row; use the explicit clear action"
        )
    return document


def validate_job_references(
    document: CategoryDocument,
    known_job_ids: set[str],
) -> None:
    definition = get_category_definition(document.category)
    if definition.key is KnowledgeCategoryKey.JOBS:
        return

    unknown = unknown_job_references(
        (getattr(record, "job_ids", []) for record in getattr(document, definition.list_field)),
        known_job_ids,
    )
    if unknown:
        raise UnknownJobReferenceError(
            f"unknown job reference(s) in this project: {', '.join(sorted(unknown))}"
        )


async def validate_active_job_references(
    db: AsyncSession,
    project_id: uuid.UUID,
    document: CategoryDocument,
) -> None:
    """Check ``document``'s job references against the project's *active* content.

    The JOBS category is checked in the other direction: every other category's
    active revision must still resolve against the job ids this document
    publishes. Anything else is checked against the active JOBS revision.
    """
    if isinstance(document, JobsDocument):
        new_job_ids = {item.id for item in document.jobs}
        sibling_categories = (
            await db.scalars(
                select(KnowledgeCategory).where(
                    KnowledgeCategory.project_id == project_id,
                    KnowledgeCategory.category_key != KnowledgeCategoryKey.JOBS.value,
                    KnowledgeCategory.active_revision_id.is_not(None),
                )
            )
        ).all()
        for sibling in sibling_categories:
            revision = await db.get(
                KnowledgeCategoryRevision,
                sibling.active_revision_id,
            )
            if revision is None:
                continue
            sibling_document = validate_category_payload(
                sibling.category_key,
                revision.normalized_payload,
            )
            validate_job_references(sibling_document, new_job_ids)
        return
    jobs_category = await db.scalar(
        select(KnowledgeCategory).where(
            KnowledgeCategory.project_id == project_id,
            KnowledgeCategory.category_key == KnowledgeCategoryKey.JOBS.value,
        )
    )
    known_ids: set[str] = set()
    if jobs_category and jobs_category.active_revision_id:
        revision = await db.get(
            KnowledgeCategoryRevision,
            jobs_category.active_revision_id,
        )
        if revision:
            known_ids = {
                str(item["id"])
                for item in revision.normalized_payload.get("jobs", [])
                if isinstance(item, dict) and item.get("id")
            }
    validate_job_references(document, known_ids)


def canonical_category_json(document: CategoryDocument) -> str:
    payload = document.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def category_checksum(document: CategoryDocument) -> str:
    return category_payload_checksum(document.model_dump(mode="json"))
