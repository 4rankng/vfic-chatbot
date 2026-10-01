"""Code-owned category identity, ordering and authoring metadata.

Transport schemas, ingestion, projections and export all consume this registry.
Record-list fields and template filenames derive from category identity so adding
one category cannot silently give those consumers different names.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.project_knowledge.domain.category import KnowledgeCategoryKey


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    key: KnowledgeCategoryKey
    label_vi: str
    # The questions candidates actually ask about this category (mirrors the
    # operator's BIỂU MẪU THU THẬP collection form). Rendered into the combined
    # KB template so a recruiter knows what each category must answer.
    leading_questions: tuple[str, ...] = ()

    @property
    def list_field(self) -> str:
        return self.key.value

    @property
    def template_filename(self) -> str:
        return f"{self.key.value}.md"


CATEGORY_DEFINITIONS: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(
        KnowledgeCategoryKey.JOBS,
        "Vị trí tuyển dụng",
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
        (
            "Có thưởng nóng hoặc thưởng đi làm không, bao nhiêu?",
            "Có du lịch hay đào tạo gì không?",
            "Phúc lợi nổi bật nào thu hút ứng viên?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.ACCOMMODATION,
        "Chỗ ở",
        (
            "Công ty có ký túc xá không?",
            "Điều kiện để ở ký túc xá là gì?",
            "Không ở KTX có được hỗ trợ tìm phòng trọ không?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.MEALS,
        "Bữa ăn",
        (
            "Đi làm có được bao ăn không, mấy bữa?",
            "Cơm ca có mất tiền không?",
            "Không ăn ca có được hỗ trợ tiền không?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.TRANSPORTATION,
        "Đưa đón & lịch xe",
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
        (
            "Có đóng BHXH không, từ khi nào?",
            "Khám sức khỏe đầu vào thế nào?",
        ),
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.APPLICATION,
        "Ứng tuyển & nhận việc",
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
        (
            "Tổng hợp các câu hỏi ứng viên hay gặp nhất theo từng giai đoạn:",
            "trước phỏng vấn, khi nhận việc, khi nghỉ việc.",
        ),
    ),
)

_DEFINITIONS_BY_KEY = {definition.key: definition for definition in CATEGORY_DEFINITIONS}


def get_category_definition(key: KnowledgeCategoryKey | str) -> CategoryDefinition:
    return _DEFINITIONS_BY_KEY[KnowledgeCategoryKey(key)]
