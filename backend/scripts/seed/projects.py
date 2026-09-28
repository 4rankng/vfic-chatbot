"""Project fixture: the four factory recruitment sites the rest hangs off."""

from __future__ import annotations

from app.models.company import Project

from .common import new_uuid


def make_projects() -> list[Project]:
    return [
        Project(
            id=new_uuid(),
            slug="lg-display-hai-phong",
            name="LG Display Hải Phòng",
            is_active=True,
            summary="Nhà máy sản xuất màn hình LCD/LED LG Display tại khu công nghiệp Tràng Duệ, Hải Phòng. Tuyển dụng công nhân sản xuất, QC, kỹ thuật bảo trì với chế độ phúc lợi tốt.",
            index_card={
                "roles": ["Công nhân sản xuất", "QC/KCS", "Kỹ thuật bảo trì", "Tổ trưởng sản xuất"],
                "location": "Hải Phòng",
                "highlights": ["Lương 7-12 triệu", "Bao ăn ở", "Xe đưa đón", "Bảo hiểm đầy đủ"],
            },
        ),
        Project(
            id=new_uuid(),
            slug="lg-display-bac-ninh",
            name="LG Display Bắc Ninh",
            is_active=True,
            summary="Nhà máy LG Display tại KCN Yên Phong, Bắc Ninh. Môi trường làm việc hiện đại, quy trình Hàn Quốc.",
            index_card={
                "roles": ["Công nhân Assembly", "Kỹ thuật viên", "QC", "Line Leader"],
                "location": "Bắc Ninh",
                "highlights": [
                    "Lương 7.5-13 triệu",
                    "Hỗ trợ ăn trưa",
                    "Bảo hiểm xã hội",
                    "Thưởng tháng 13",
                ],
            },
        ),
        Project(
            id=new_uuid(),
            slug="samsung-bac-ninh",
            name="Samsung Bắc Ninh",
            is_active=True,
            summary="Khu phức hợp Samsung tại KCN Yên Phong, Bắc Ninh. Tuyển dụng quy mô lớn liên tục.",
            index_card={
                "roles": ["Công nhân SMT", "Công nhân đóng gói", "KCS", "Tổ trưởng"],
                "location": "Bắc Ninh",
                "highlights": ["Lương 7-11 triệu", "Bao ăn ở", "Xe đưa đón", "Thưởng KPI"],
            },
        ),
        Project(
            id=new_uuid(),
            slug="foxconn-nghe-an",
            name="Foxconn Nghệ An",
            is_active=True,
            summary="Nhà máy Foxconn tại Khu kinh tế Đông Nam, Nghệ An. Sản xuất linh kiện điện tử.",
            index_card={
                "roles": ["Công nhân lắp ráp", "Kỹ thuật viên", "QC", "Kho vận"],
                "location": "Nghệ An",
                "highlights": ["Lương 6.5-10 triệu", "Hỗ trợ nhà ở", "Bảo hiểm", "Làm thêm giờ"],
            },
        ),
    ]
