"""Knowledge fixture: published FAQ/timetable documents and their chunks."""

from __future__ import annotations

from app.models.company import Project
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeStatus

from .common import new_uuid, rng


def make_knowledge_documents(projects: list[Project]) -> list[KnowledgeDocument]:
    docs = [
        KnowledgeDocument(
            id=new_uuid(),
            project_id=projects[0].id,
            file_name="lgd-faq.md",
            source="upload",
            status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# FAQ LG Display Hải Phòng\n\n## Lương\nMức lương từ 7-12 triệu tùy ca và vị trí...\n\n## Chỗ ở\nCó ký túc xá cho công nhân...",
            metadata_={"schema_version": "1", "type": "faq"},
            mime_type="text/markdown",
            digest_summary="FAQ tổng hợp về tuyển dụng LG Display Hải Phòng",
        ),
        KnowledgeDocument(
            id=new_uuid(),
            project_id=projects[0].id,
            file_name="lgd-bus-timetable.md",
            source="upload",
            status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# Lịch xe bus đưa đón LG Display\n\n## Tuyến Hải Phòng\n5h15, 5h45, 13h00...",
            metadata_={"schema_version": "1", "type": "bus_timetable"},
            mime_type="text/markdown",
            digest_summary="Lịch xe đưa đón chi tiết cho công nhân LG Display",
        ),
        KnowledgeDocument(
            id=new_uuid(),
            project_id=projects[1].id,
            file_name="lgd-bn-faq.md",
            source="upload",
            status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# FAQ LG Display Bắc Ninh\n\n## Mức lương\n7.5-13 triệu...\n\n## Phúc lợi\nHỗ trợ ăn ở, xe đưa đón...",
            metadata_={"schema_version": "1", "type": "faq"},
            mime_type="text/markdown",
            digest_summary="FAQ tuyển dụng LG Display Bắc Ninh",
        ),
        KnowledgeDocument(
            id=new_uuid(),
            project_id=projects[2].id,
            file_name="samsung-bn-info.md",
            source="upload",
            status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# Thông tin tuyển dụng Samsung Bắc Ninh\n\n## Tổng quan\nKhu phức hợp sản xuất lớn nhất Samsung tại VN...",
            metadata_={"schema_version": "1", "type": "faq"},
            mime_type="text/markdown",
            digest_summary="Thông tin tổng quan tuyển dụng Samsung Bắc Ninh",
        ),
        KnowledgeDocument(
            id=new_uuid(),
            project_id=projects[3].id,
            file_name="foxconn-na-info.md",
            source="upload",
            status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# Foxconn Nghệ An - Thông tin tuyển dụng\n\n## Tổng quan\nNhà máy sản xuất linh kiện điện tử...",
            metadata_={"schema_version": "1", "type": "faq"},
            mime_type="text/markdown",
            digest_summary="Thông tin tuyển dụng Foxconn Nghệ An",
        ),
        KnowledgeDocument(
            id=new_uuid(),
            project_id=None,
            file_name="vfic-general-policy.md",
            source="upload",
            status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# Chính sách chung VFIC\n\n## Quy trình ứng tuyển\n1. Đăng ký qua Zalo\n2. Phỏng vấn trực tiếp\n3. Khám sức khỏe\n4. Nhận việc...",
            metadata_={"schema_version": "1", "type": "policy"},
            mime_type="text/markdown",
            digest_summary="Chính sách và quy trình tuyển dụng chung VFIC",
        ),
    ]
    return docs


def make_knowledge_chunks(docs: list[KnowledgeDocument]) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    chunk_specs = [
        (
            "Lương cơ bản từ 7-12 triệu VNĐ/tháng tùy ca làm việc và vị trí. Ca 3 vòng lương 7-9 triệu, ca 4 lương 9-12 triệu.",
            "faq",
            {"topic": "lương"},
        ),
        (
            "Nhà máy hỗ trợ bao ăn ở cho công nhân ngoại tỉnh. Ký túc xá 6 người/phòng, có điều hòa, nóng lạnh.",
            "faq",
            {"topic": "chỗ ở"},
        ),
        (
            "Xe đưa đón miễn phí từ Hải Phòng, Thái Bình, Nam Định, Hà Nội. Lịch xe: 5h15, 5h45, 13h00 hàng ngày.",
            "faq",
            {"topic": "xe đưa đón"},
        ),
        (
            "Đóng đầy đủ bảo hiểm xã hội, sức khỏe, thất nghiệp theo quy định pháp luật Việt Nam.",
            "faq",
            {"topic": "bảo hiểm"},
        ),
        (
            "Thưởng tháng 13 hàng năm, thưởng KPI hàng quý. Cho phép làm thêm giờ với mức x1.5 - x2.",
            "faq",
            {"topic": "thưởng"},
        ),
        (
            "Quy trình ứng tuyển: 1) Đăng ký qua Zalo 2) Phỏng vấn 3) Khám sức khỏe 4) Nhận việc trong 3-5 ngày.",
            "policy",
            {"topic": "quy trình"},
        ),
        (
            "Thời gian thử việc 2 tháng, lương bằng 85% lương chính thức. Sau thử việc ký hợp đồng 12 tháng.",
            "policy",
            {"topic": "thử việc"},
        ),
        (
            "Yêu cầu: tuổi 18-45, không yêu cầu kinh nghiệm cho công nhân sản xuất. Biết đọc viết, làm việc nhóm.",
            "faq",
            {"topic": "yêu cầu"},
        ),
    ]

    for i, doc in enumerate(docs):
        # 2-3 chunks per document
        for j in range(rng.randint(2, 3)):
            spec = chunk_specs[(i * 3 + j) % len(chunk_specs)]
            chunks.append(
                KnowledgeChunk(
                    id=new_uuid(),
                    document_id=doc.id,
                    chunk_index=j,
                    content=spec[0],
                    project_id=doc.project_id,
                    source_quote=spec[0][:100],
                    summary=spec[0],
                    questions=[f"Câu hỏi về {spec[2].get('topic', 'thông tin')}"],
                    category=spec[1],
                    entities=spec[2],
                    confidence="high",
                    search_text=spec[0].lower(),
                    metadata_={},
                )
            )
    return chunks
