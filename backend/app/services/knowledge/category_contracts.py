"""Deterministic validation helpers for project-owned RAG category documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.knowledge_categories import (
    CATEGORY_DOCUMENT_MODELS,
    MAX_CATEGORY_RECORDS,
    CategoryDocument,
)
from app.project_knowledge.domain.category import (
    KnowledgeCategoryKey,
    category_payload_checksum,
    category_record_limit_exceeded,
    category_replacement_is_empty,
)
from app.project_knowledge.domain.category_catalog import (
    CATEGORY_DEFINITIONS,
    CategoryDefinition as CategoryDefinition,
    get_category_definition as get_category_definition,
)
from app.project_knowledge.domain.legacy_job_references import strip_legacy_job_reference_fields
from app.services.knowledge.text_ingestion import normalize_kb_value


_TEMPLATE_DIR = Path(__file__).with_name("templates") / "categories"


class EmptyCategoryError(ValueError):
    """Raised when replacement content has no rows and clear was not requested."""


class CategoryMarkdownError(ValueError):
    """Raised when category content is not one well-formed Category Markdown v1 document."""


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
        "ĐỊNH DẠNG CHÍNH XÁC MÀ HỆ THỐNG ĐỌC ĐƯỢC:",
        "1. Mỗi danh mục là MỘT khối tiêu đề '## <tên danh mục>' đúng như trong mẫu (vd: `## jobs`).",
        "2. Mỗi dòng dữ liệu là một khối `### record: <ten-ngan>` (chữ thường, dấu gạch ngang,",
        "   tối đa 64 ký tự) kèm ĐÚNG các trường nêu trong khối ví dụ của danh mục đó.",
        "3. Danh sách trống ghi `[]` (vd: `aliases: []`); danh sách có dữ liệu ghi mỗi dòng một mục:",
        "   `keywords:` rồi thụt vào `- \"từ khóa\"`.",
        "4. Front-matter `---` + `schema_version`/`category` KHÔNG bắt buộc — giữ nguyên nếu có.",
        "5. Hướng dẫn chỉ đặt trong chú thích `<!-- -->` (bị bỏ qua khi đọc);",
        "   DÒNG `# ...` NGOÀI THÂN BÀI không được dùng làm chú thích.",
        "",
        "Ví dụ một tệp hoàn chỉnh đọc được ngay:",
        "\n".join(
            [
                "<!--",
                "## jobs",
                "",
                "### record: vi-cong-nhan",
                'title: "Công nhân sản xuất"',
                "aliases: []",
                'location: "KCN VSIP, Thủy Nguyên, Hải Phòng"',
                'summary: "Lắp ráp linh kiện điện tử, có đào tạo từ đầu."',
                "keywords: []",
                "",
                "## contacts",
                "",
                "### record: lien-he-chung",
                'name: "[Họ tên người phụ trách?]"',
                'role: "[Vai trò? Ví dụ: Cán bộ phụ trách hồ sơ]"',
                'phone: "[Số điện thoại?]"',
                'zalo: "[Zalo?]"',
                'email: "[Email?]"',
                'address: "[Địa chỉ tiếp nhận?]"',
                'working_hours: "[Giờ làm việc?]"',
                'notes: "[Ghi chú thêm?]"',
                "-->",
            ]
        ),
        "",
        "CÁCH LÀM:",
        "1. Sao chép khối ví dụ trong <!-- --> của từng mục ra ngoài, rồi thay nội dung trong",
        "   [ngoặc] bằng dữ liệu thật của dự án. GHI TIẾNG VIỆT CÓ DẤU đầy đủ.",
        "2. Xóa danh mục không có dữ liệu — đừng để khối trống.",
        "3. Tải tệp này lên phần Kiến thức của dự án; tệp gồm nhiều mục nạp một lần là đủ.",
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
    normalized_payload = normalize_kb_value(strip_legacy_job_reference_fields(payload))
    document = CATEGORY_DOCUMENT_MODELS[category_key].model_validate(normalized_payload)
    if not allow_empty and category_replacement_is_empty(
        len(getattr(document, definition.list_field))
    ):
        raise EmptyCategoryError(
            "category replacement must contain at least one row; use the explicit clear action"
        )
    return document


def canonical_category_json(document: CategoryDocument) -> str:
    payload = document.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def category_checksum(document: CategoryDocument) -> str:
    return category_payload_checksum(document.model_dump(mode="json"))
