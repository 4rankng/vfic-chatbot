#!/usr/bin/env python3
"""Seed the local dev database with realistic Vietnamese recruitment data.

Idempotent: truncates all seed-owned tables then inserts fresh data.
Only safe for LOCAL development — never run against production.

Usage:
    cd backend
    python -m scripts.seed_dev

Or from repo root:
    make seed
"""
from __future__ import annotations

import asyncio
import random
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Ensure backend package is importable when running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password_sync  # noqa: E402
from app.models.audit import AuditEvent  # noqa: E402
from app.models.company import Company, Project  # noqa: E402
from app.models.conversation import (  # noqa: E402
    BotRun,
    BotRunOutcome,
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.job import Job, JobStatus  # noqa: E402
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeStatus  # noqa: E402
from app.models.lead import FollowUpTask, FollowupStatus, Lead, LeadEvent, LeadScore, LeadStage  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog  # noqa: E402

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
NOW = datetime.now(timezone.utc)
TODAY = NOW.date()
rng = random.Random(42)  # deterministic seed for reproducibility


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


def hours_ago(n: float) -> datetime:
    return NOW - timedelta(hours=n)


# ---------------------------------------------------------------------------
# Data factories
# ---------------------------------------------------------------------------

def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def make_users() -> list[User]:
    pw = hash_password_sync("admin123")
    return [
        User(id=_uuid(), email="admin@vfic.dev", password_hash=pw,
             full_name="Nguyễn Văn Admin", role=Role.admin,
             token_version=0, disabled=False),
        User(id=_uuid(), email="lan.nguyen@vfic.dev", password_hash=pw,
             full_name="Nguyễn Thị Lan", role=Role.recruiter,
             token_version=0, disabled=False),
        User(id=_uuid(), email="minh.tran@vfic.dev", password_hash=pw,
             full_name="Trần Văn Minh", role=Role.recruiter,
             token_version=0, disabled=False),
    ]


def make_projects() -> list[Project]:
    return [
        Project(id=_uuid(), slug="lg-display-hai-phong", name="LG Display Hải Phòng",
                is_active=True,
                summary="Nhà máy sản xuất màn hình LCD/LED LG Display tại khu công nghiệp Tràng Duệ, Hải Phòng. Tuyển dụng công nhân sản xuất, QC, kỹ thuật bảo trì với chế độ phúc lợi tốt.",
                index_card={
                    "roles": ["Công nhân sản xuất", "QC/KCS", "Kỹ thuật bảo trì", "Tổ trưởng sản xuất"],
                    "location": "Hải Phòng",
                    "highlights": ["Lương 7-12 triệu", "Bao ăn ở", "Xe đưa đón", "Bảo hiểm đầy đủ"],
                }),
        Project(id=_uuid(), slug="lg-display-bac-ninh", name="LG Display Bắc Ninh",
                is_active=True,
                summary="Nhà máy LG Display tại KCN Yên Phong, Bắc Ninh. Môi trường làm việc hiện đại, quy trình Hàn Quốc.",
                index_card={
                    "roles": ["Công nhân Assembly", "Kỹ thuật viên", "QC", "Line Leader"],
                    "location": "Bắc Ninh",
                    "highlights": ["Lương 7.5-13 triệu", "Hỗ trợ ăn trưa", "Bảo hiểm xã hội", "Thưởng tháng 13"],
                }),
        Project(id=_uuid(), slug="samsung-bac-ning", name="Samsung Bắc Ninh",
                is_active=True,
                summary="Khu phức hợp Samsung tại KCN Yên Phong, Bắc Ninh. Tuyển dụng quy mô lớn liên tục.",
                index_card={
                    "roles": ["Công nhân SMT", "Công nhân đóng gói", "KCS", "Tổ trưởng"],
                    "location": "Bắc Ninh",
                    "highlights": ["Lương 7-11 triệu", "Bao ăn ở", "Xe đưa đón", "Thưởng KPI"],
                }),
        Project(id=_uuid(), slug="foxconn-nghe-an", name="Foxconn Nghệ An",
                is_active=True,
                summary="Nhà máy Foxconn tại Khu kinh tế Đông Nam, Nghệ An. Sản xuất linh kiện điện tử.",
                index_card={
                    "roles": ["Công nhân lắp ráp", "Kỹ thuật viên", "QC", "Kho vận"],
                    "location": "Nghệ An",
                    "highlights": ["Lương 6.5-10 triệu", "Hỗ trợ nhà ở", "Bảo hiểm", "Làm thêm giờ"],
                }),
    ]


def make_companies(projects: list[Project]) -> list[Company]:
    """One company per project (the factory operator)."""
    companies = []
    for p in projects:
        companies.append(
            Company(id=_uuid(), project_id=p.id, name=f"Cty TNHH {p.name}", aliases=[p.name]),
        )
    return companies


def make_personas(users: list[User]) -> list[Persona]:
    return [
        Persona(
            id=_uuid(), project_id=None, name="VFIC Bot mặc định", slug="default-vfic",
            body_md=(
                "# VFIC Tư vấn viên tuyển dụng\n\n"
                "Bạn là trợ lý tuyển dụng của VFIC. Hãy tư vấn cho ứng viên một cách "
                "chuyên nghiệp, thân thiện, bằng tiếng Việt.\n\n"
                "## Phong cách\n"
                "- Gọi ứng viên là 'bạn'\n"
                "- Trả lời ngắn gọn, rõ ràng\n"
                "- Luôn dựa trên dữ liệu thực tế từ hệ thống\n"
                "- Không đưa thông tin không có trong dữ liệu\n"
            ),
            is_active=True, created_by=users[0].id,
        ),
        Persona(
            id=_uuid(), project_id=None, name="LG Display tư vấn viên", slug="lg-display",
            body_md=(
                "# LG Display Tuyển dụng\n\n"
                "Bạn là tư vấn viên chuyên tuyển dụng cho nhà máy LG Display. "
                "Thông tin chi tiết về các nhà máy, lương thưởng, phúc lợi.\n\n"
                "## Yêu cầu\n"
                "- Chỉ tư vấn về LG Display\n"
                "- Dữ liệu bám sát bus timetable, lương, phúc lợi\n"
            ),
            is_active=False, created_by=users[0].id,
        ),
    ]


def make_jobs(companies: list[Company]) -> list[Job]:
    specs = [
        ("Công nhân sản xuất LCD", "Hải Phòng", "Thành phố Hồ Chí Minh", None, 7_000_000, 12_000_000, "Ca 3 vòng / Ca 4 vòng", "Nam/Nữ", 18, 45, "Không yêu cầu kinh nghiệm", True, True, True, 50),
        ("Công nhân Assembly", "Bắc Ninh", "Thuận Thành", None, 7_500_000, 13_000_000, "Ca 3 vòng", "Nam/Nữ", 18, 40, "Không yêu cầu kinh nghiệm", True, True, True, 80),
        ("Công nhân SMT", "Bắc Ninh", "Yên Phong", None, 7_000_000, 11_000_000, "Ca 3 vòng / Ca 2 vòng", "Nam ưu tiên", 18, 45, "Không yêu cầu", True, True, True, 120),
        ("QC/KCS chất lượng", "Bắc Ninh", "Yên Phong", None, 8_500_000, 14_000_000, "Ca ngày", "Nam/Nữ", 20, 35, "1 năm kinh nghiệm QC", True, True, False, 15),
        ("Kỹ thuật bảo trì", "Hải Phòng", "An Dương", None, 10_000_000, 18_000_000, "Ca ngày", "Nam", 22, 45, "2 năm kinh nghiệm bảo trì thiết bị", True, True, False, 10),
        ("Công nhân đóng gói", "Bắc Ninh", "Quế Võ", None, 6_500_000, 9_000_000, "Ca 2 vòng", "Nữ ưu tiên", 18, 40, "Không yêu cầu", False, True, True, 60),
        ("Công nhân lắp ráp điện tử", "Nghệ An", "TX Hoàng Mai", None, 6_500_000, 10_000_000, "Ca 3 vòng", "Nam/Nữ", 18, 45, "Không yêu cầu kinh nghiệm", True, True, True, 90),
        ("Tổ trưởng sản xuất", "Hải Phòng", "Thành phố Hồ Chí Minh", None, 15_000_000, 22_000_000, "Ca ngày", "Nam/Nữ", 25, 50, "3 năm kinh nghiệm, biết quản lý line", True, True, False, 5),
        ("Kỹ thuật viên", "Nghệ An", "TX Hoàng Mai", None, 9_000_000, 15_000_000, "Ca ngày", "Nam", 20, 40, "1 năm kinh nghiệm sửa chữa máy móc", True, True, False, 12),
        ("Công nhân kho vận", "Bắc Ninh", "Yên Phong", None, 7_000_000, 10_000_000, "Ca ngày", "Nam", 18, 45, "Không yêu cầu", False, True, True, 20),
    ]
    jobs: list[Job] = []
    for i, (title, province, district, address, sal_min, sal_max, shift, gender,
            age_min, age_max, exp, accom, meal, transport, vacancy) in enumerate(specs):
        company = companies[i % len(companies)]
        jobs.append(Job(
            id=_uuid(), company_id=company.id,
            title=title, factory_name=company.name,
            province=province, district=district, address=address,
            salary_min=sal_min, salary_max=sal_max, shift=shift,
            gender_requirement=gender, age_min=age_min, age_max=age_max,
            experience_required=exp,
            accommodation_support=accom, meal_support=meal,
            transport_support=transport, vacancy_count=vacancy,
            status=JobStatus.ACTIVE,
            description=f"Tuyển {vacancy} {title} làm việc tại {province}. {shift}, "
                       f"lương {sal_min // 1_000_000}-{sal_max // 1_000_000} triệu.",
            requirements=f"Tuổi {age_min}-{age_max}. {exp}. Ưu tiên biết đọc số, làm việc nhóm.",
            benefits="Bảo hiểm xã hội, sức khỏe, thất nghiệp. Thưởng tháng 13. Đóng góp quỹ hưu trí.",
        ))
    return jobs


def make_worker_features() -> list[WorkerFeatureCatalog]:
    features = [
        ("salary", "Mức lương", "Thu nhập", "Lương bao nhiêu ạ?", "Mức lương cơ bản và tổng thu nhập hàng tháng", 0.95),
        ("accommodation", "Chỗ ở", "Phúc lợi", "Có bao ăn ở không ạ?", "Hỗ trợ chỗ ở cho công nhân xa nhà", 0.90),
        ("transport", "Xe đưa đón", "Phúc lợi", "Có xe đưa đón không?", "Xe đưa đón từ các điểm tập kết", 0.85),
        ("meal", "Bữa ăn", "Phúc lợi", "Có hỗ trợ ăn không ạ?", "Hỗ trợ bữa ăn trưa tại xưởng", 0.80),
        ("insurance", "Bảo hiểm", "Phúc lợi", "Có đóng bảo hiểm không?", "Bảo hiểm xã hội, sức khỏe, thất nghiệp", 0.85),
        ("shift", "Ca làm việc", "Thời gian", "Làm việc mấy ca ạ?", "Ca 2, ca 3 hoặc ca 4 tùy nhà máy", 0.80),
        ("bonus", "Thưởng", "Thu nhập", "Có thưởng không ạ?", "Thưởng tháng 13, KPI, hiệu quả", 0.70),
        ("overtime", "Làm thêm giờ", "Thời gian", "Có làm thêm giờ không?", "Cho phép làm thêm với mức lương x1.5", 0.75),
        ("contract", "Hợp đồng", "Hành chính", "Ký hợp đồng kiểu gì ạ?", "Hợp đồng lao động theo luật Việt Nam", 0.65),
        ("probation", "Thử việc", "Hành chính", "Thời gian thử việc bao lâu?", "Thường 1-2 tháng thử việc", 0.60),
        ("training", "Đào tạo", "Phát triển", "Có đào tạo không ạ?", "Đào tạo tay nghề và an toàn lao động", 0.55),
        ("uniform", "Đồng phục", "Khác", "Có cấp đồng phục không ạ?", "Cấp 2 bộ đồng phục/năm", 0.40),
        ("contact_info", "Thông tin liên hệ", "Hành chính", "Làm sao để đăng ký ạ?", "Thông tin đăng ký và liên hệ nhà máy", 0.70),
        ("bus_timetable", "Lịch xe bus", "Phúc lợi", "Xe bus mấy giờ chạy ạ?", "Lịch trình xe đưa đón chi tiết", 0.90),
    ]
    return [
        WorkerFeatureCatalog(
            id=_uuid(), feature_key=key, name_vi=name, category=cat,
            worker_question_vi=question, description=desc,
            default_importance_score=importance, is_active=True,
        )
        for key, name, cat, question, desc, importance in features
    ]


def make_job_feature_values(
    projects: list[Project],
    features: list[WorkerFeatureCatalog],
) -> list[JobFeatureValue]:
    """Populate feature values per project."""
    values: list[JobFeatureValue] = []
    feat_map = {f.feature_key: f.id for f in features}

    # LG Hải Phòng
    lg_hp = projects[0].id
    lg_hp_vals = {
        "salary": ("7-12 triệu (tùy ca và kinh nghiệm)", {"min": 7, "max": 12, "unit": "triệu VNĐ"}, 0.95, True),
        "accommodation": ("Có bao ở — ký túc xá công nhân, 6 người/phòng", {"type": "ký túc xá", "capacity": "6 người/phòng"}, 0.90, True),
        "transport": ("Có xe đưa đón từ Hải Phòng, Thái Bình, Nam Định, Hà Nội", {"routes": ["HP", "TB", "ND", "HN"]}, 0.88, True),
        "meal": ("Hỗ trợ bữa ăn trưa tại nhà máy, 25.000 VNĐ/bữa", {"amount": 25000, "type": "ăn trưa"}, 0.80, False),
        "insurance": ("Đóng đầy đủ BHXH, BHYT, BHTN theo luật", {"types": ["BHXH", "BHYT", "BHTN"]}, 0.85, False),
        "shift": ("Ca 3 vòng: 6h-14h / 14h-22h / 22h-6h hoặc ca 4", {"types": ["ca 3", "ca 4"]}, 0.80, False),
        "bonus": ("Thưởng tháng 13, thưởng KPI hàng quý", {"types": ["tháng 13", "KPI"]}, 0.75, False),
        "overtime": ("Được làm thêm giờ, lương x1.5 ngày thường, x2 ngày lễ", {"rates": {"normal": 1.5, "holiday": 2.0}}, 0.70, False),
        "contract": ("HĐ 12 tháng, renew tự động. Thử việc 2 tháng = 85% lương", {"type": "12 tháng", "probation_rate": 0.85}, 0.65, False),
        "probation": ("2 tháng thử việc, lương bằng 85%", {"duration": "2 tháng", "rate": "85%"}, 0.60, False),
        "bus_timetable": ("Xe 5h15, 5h45, 13h00 từ Hải Phòng; 5h30, 6h00 từ Thái Bình", {}, 0.92, True),
    }
    for key, (val_text, val_json, strength, highlight) in lg_hp_vals.items():
        if key in feat_map:
            values.append(JobFeatureValue(
                id=_uuid(), project_id=lg_hp, feature_id=feat_map[key],
                value_text=val_text, value_json=val_json,
                strength_score=strength, display_priority=100 - values.__len__() % 10,
                is_highlight=highlight,
            ))

    # LG Bắc Ninh
    lg_bn = projects[1].id
    lg_bn_vals = {
        "salary": ("7.5-13 triệu (ca 3: 8-10tr, ca ngày: 10-13tr)", {"min": 7.5, "max": 13}, 0.95, True),
        "accommodation": ("Hỗ trợ nhà ở 500.000 VNĐ/tháng cho người ngoại tỉnh", {"allowance": 500000}, 0.85, True),
        "transport": ("Xe đưa đón từ Hà Nội, Bắc Ninh, Bắc Giang, Thái Nguyên", {"routes": ["HN", "BN", "BG", "TN"]}, 0.88, True),
        "meal": ("Cấp 25.000 VNĐ ăn trưa, nhà máy có canteen", {"amount": 25000}, 0.80, False),
        "insurance": ("BHXH, BHYT, BHTN đầy đủ", {}, 0.85, False),
        "shift": ("Ca 3 vòng chính, mỗi ca 8 tiếng", {"types": ["ca 3"]}, 0.80, False),
        "bonus": ("Thưởng tháng 13 + thưởng hiệu quả sản xuất", {}, 0.75, False),
        "contract": ("HĐ 12 tháng, thử việc 60 ngày = 85%", {}, 0.65, False),
        "bus_timetable": ("Xe 5h00, 5h30, 6h00 từ các tỉnh, xe tăng vào mùa tuyển", {}, 0.90, True),
    }
    for key, (val_text, val_json, strength, highlight) in lg_bn_vals.items():
        if key in feat_map:
            values.append(JobFeatureValue(
                id=_uuid(), project_id=lg_bn, feature_id=feat_map[key],
                value_text=val_text, value_json=val_json,
                strength_score=strength, display_priority=100 - values.__len__() % 10,
                is_highlight=highlight,
            ))

    # Samsung
    sam = projects[2].id
    sam_vals = {
        "salary": ("7-11 triệu + thưởng KPI 500k-1.5tr/tháng", {"min": 7, "max": 11, "bonus": "500k-1.5tr"}, 0.95, True),
        "accommodation": ("Bao ở — ký túc xá 4-6 người/phòng, có điều hòa", {"capacity": "4-6 người"}, 0.92, True),
        "transport": ("Xe đưa đón miễn phí từ 8 tỉnh", {}, 0.88, True),
        "meal": ("3 bữa/ngày, ăn tại canteen", {}, 0.82, True),
        "insurance": ("BHXH + BHYT + BHTN + Bảo hiểm tai nạn", {}, 0.85, False),
        "shift": ("Ca 3 vòng hoặc ca 2 vòng sáng-chiều", {}, 0.80, False),
        "bonus": ("Tháng 13 + thưởng sản xuất + thưởng chuyên cần", {}, 0.78, False),
        "contract": ("HĐ xác định thời hạn 1 năm, thử việc 2 tháng", {}, 0.65, False),
    }
    for key, (val_text, val_json, strength, highlight) in sam_vals.items():
        if key in feat_map:
            values.append(JobFeatureValue(
                id=_uuid(), project_id=sam, feature_id=feat_map[key],
                value_text=val_text, value_json=val_json,
                strength_score=strength, display_priority=100 - values.__len__() % 10,
                is_highlight=highlight,
            ))

    # Foxconn Nghệ An
    fc = projects[3].id
    fc_vals = {
        "salary": ("6.5-10 triệu + làm thêm giờ nhiều", {"min": 6.5, "max": 10}, 0.95, True),
        "accommodation": ("Hỗ trợ 400.000 VNĐ/tháng nhà ở", {"allowance": 400000}, 0.80, True),
        "transport": ("Có xe đưa đón từ Vinh, Hà Tĩnh, Quảng Bình", {}, 0.85, True),
        "meal": ("Hỗ trợ 20.000 VNĐ/bữa ăn trưa", {}, 0.78, False),
        "insurance": ("BHXH đầy đủ theo quy định", {}, 0.82, False),
        "shift": ("Ca 3 vòng, 8 tiếng/ca", {}, 0.80, False),
        "contract": ("HĐ 12 tháng, thử việc 60 ngày = 85%", {}, 0.65, False),
    }
    for key, (val_text, val_json, strength, highlight) in fc_vals.items():
        if key in feat_map:
            values.append(JobFeatureValue(
                id=_uuid(), project_id=fc, feature_id=feat_map[key],
                value_text=val_text, value_json=val_json,
                strength_score=strength, display_priority=100 - values.__len__() % 10,
                is_highlight=highlight,
            ))

    return values


def make_leads(users: list[User], jobs: list[Job], convos: list[Conversation]) -> list[Lead]:
    """Generate 35 leads across all stages with Vietnamese names.

    The first 25 leads link to the seeded conversations via zalo_id (FK to
    conversations.zalo_chat_id). Remaining 10 leads have zalo_id=None (candidates
    who haven't chatted yet — e.g. inbound from other channels or manual entry).
    """
    first_names_m = ["Nguyễn Văn", "Trần Đức", "Phạm Hoàng", "Lê Quang", "Hoàng Minh",
                      "Đặng Thanh", "Vũ Đình", "Bùi Xuân", "Đỗ Anh", "Lý Quốc",
                      "Phan Thành", "Trịnh Duy", "Ngô Minh", "Huỳnh Quang", "Hà Văn"]
    first_names_f = ["Nguyễn Thị", "Trần Thu", "Phạm Lan", "Lê Mai", "Hoàng Thu",
                      "Đặng Hương", "Vũ Ngọc", "Bùi Thảo", "Đỗ Kim", "Lý Hoa",
                      "Phan Tâm", "Trịnh Ánh", "Ngô Liên", "Huỳnh Nhung", "Hà Phương"]
    last_names = ["An", "Bình", "Cường", "Dũng", "Em", "Phúc", "Giang", "Hải",
                  "Khôi", "Linh", "Mai", "Nam", "Oanh", "Phong", "Quân",
                  "Sơn", "Tâm", "Uyên", "Vinh", "Yến"]
    living_areas = ["Hải Phòng", "Thái Bình", "Nam Định", "Hà Nội", "Bắc Ninh",
                    "Bắc Giang", "Hải Dương", "Hưng Yên", "Vĩnh Phúc", "Quảng Ninh",
                    "Nghệ An", "Hà Tĩnh", "Thanh Hóa", "Nghệ An", "Kon Tum"]
    desired_jobs = ["Công nhân sản xuất", "Công nhân lắp ráp", "QC/KCS",
                     "Công nhân đóng gói", "Kỹ thuật viên", "Công nhân SMT",
                     "Công nhân kho vận"]
    stages_weights = [
        (LeadStage.NEW, 8),
        (LeadStage.ENGAGED, 7),
        (LeadStage.QUALIFIED, 5),
        (LeadStage.APPLIED, 4),
        (LeadStage.HIRED, 3),
        (LeadStage.LOST, 5),
        (LeadStage.UNQUALIFIED, 3),
    ]

    stages_pool: list[LeadStage] = []
    for stage, count in stages_weights:
        stages_pool.extend([stage] * count)

    leads: list[Lead] = []
    for i in range(35):
        gender = "Nam" if i % 3 != 0 else "Nữ"
        names_pool = first_names_m if gender == "Nam" else first_names_f
        full = f"{names_pool[i % len(names_pool)]} {last_names[i % len(last_names)]}"
        stage = stages_pool[i]
        # Link to a conversation if available (first 25 leads match 25 convos)
        zalo_id = convos[i % len(convos)].zalo_chat_id if i < len(convos) else None
        created = days_ago(rng.randint(1, 30))

        score_map = {
            LeadStage.NEW: None,
            LeadStage.ENGAGED: LeadScore.warm,
            LeadStage.QUALIFIED: LeadScore.hot,
            LeadStage.APPLIED: LeadScore.hot,
            LeadStage.HIRED: LeadScore.hot,
            LeadStage.LOST: LeadScore.not_interested,
            LeadStage.UNQUALIFIED: LeadScore.not_interested,
        }

        lead = Lead(
            zalo_id=zalo_id,
            name=full,
            phone=f"0{rng.randint(30, 79)}{rng.randint(1000000, 9999999)}" if i % 2 == 0 else None,
            age=rng.randint(19, 42),
            birth_year=1990 + rng.randint(-10, 10),
            living_area=living_areas[i % len(living_areas)],
            gender=gender,
            region=living_areas[i % len(living_areas)],
            desired_job=desired_jobs[i % len(desired_jobs)],
            years_experience=f"{rng.randint(0, 5)} năm" if rng.random() > 0.4 else "Chưa có kinh nghiệm",
            expected_salary=f"{rng.randint(6, 12)} triệu" if rng.random() > 0.3 else None,
            lead_score=score_map[stage],
            lead_stage=stage,
            intent_score=round(rng.uniform(0.3, 1.0), 2) if stage in (LeadStage.QUALIFIED, LeadStage.APPLIED, LeadStage.HIRED) else None,
            qualification_reasons=["Đạt yêu cầu tuổi", "Có kinh nghiệm"] if stage == LeadStage.QUALIFIED else [],
            assigned_recruiter_id=users[1 + (i % 2)].id if stage in (LeadStage.ENGAGED, LeadStage.QUALIFIED, LeadStage.APPLIED) else None,
            notes=None,
            created_at=created,
            updated_at=created + timedelta(hours=rng.randint(1, 48)),
        )
        if stage == LeadStage.LOST:
            lead.notes = "Không liên lạc được sau 3 lần gọi"
        elif stage == LeadStage.UNQUALIFIED:
            lead.notes = "Ngoài độ tuổi quy định"
        leads.append(lead)
    return leads


def make_lead_events(leads: list[Lead], users: list[User]) -> list[LeadEvent]:
    events: list[LeadEvent] = []
    event_types_by_stage: dict[LeadStage, list[str]] = {
        LeadStage.NEW: ["created", "auto_tag"],
        LeadStage.ENGAGED: ["created", "auto_tag", "first_contact", "followed_up"],
        LeadStage.QUALIFIED: ["created", "auto_tag", "first_contact", "followed_up", "qualified"],
        LeadStage.APPLIED: ["created", "auto_tag", "first_contact", "qualified", "applied"],
        LeadStage.HIRED: ["created", "auto_tag", "first_contact", "qualified", "applied", "hired"],
        LeadStage.LOST: ["created", "auto_tag", "first_contact", "lost"],
        LeadStage.UNQUALIFIED: ["created", "auto_tag", "unqualified"],
    }

    for lead in leads:
        etypes = event_types_by_stage.get(lead.lead_stage, ["created"])
        for j, etype in enumerate(etypes):
            events.append(LeadEvent(
                lead_id=lead.id,
                event_type=etype,
                payload={"source": "zalo", "note": f"{etype} event"},
                actor_id=users[1].id if j > 0 else None,
                created_at=lead.created_at + timedelta(hours=j),
            ))
    return events


def make_followup_tasks(leads: list[Lead], users: list[User]) -> list[FollowUpTask]:
    tasks: list[FollowUpTask] = []
    for i, lead in enumerate(leads):
        if lead.lead_stage in (LeadStage.ENGAGED, LeadStage.QUALIFIED, LeadStage.APPLIED):
            tasks.append(FollowUpTask(
                lead_id=lead.id,
                due_at=hours_ago(-rng.randint(1, 72)) if lead.lead_stage == LeadStage.APPLIED else hours_ago(-rng.randint(-48, 24)),
                note="Gọi lại hỏi tiến độ hồ sơ" if lead.lead_stage == LeadStage.APPLIED else "Liên hệ tư vấn chi tiết công việc",
                status=rng.choice([FollowupStatus.PENDING, FollowupStatus.DONE]),
                created_by=users[1 + (i % 2)].id,
                completed_at=hours_ago(2) if rng.random() > 0.5 else None,
            ))
    return tasks


def make_conversations(users: list[User]) -> list[Conversation]:
    convos: list[Conversation] = []
    modes = [ConversationMode.BOT, ConversationMode.BOT, ConversationMode.BOT,
             ConversationMode.HUMAN, ConversationMode.SEMI_AUTO, ConversationMode.CLOSED]
    names = ["Anh Tuấn", "Chị Mai", "Lan Anh", "Anh Hoàng", "Minh Quân", "Thu Hà",
             "Đức Trí", "Bích Ngọc", "Thành Đạt", "Hương Giang", "Quốc Bảo", "Phương Linh",
             "Văn Kiệt", "Thảo Vy", "Xuân Hạnh", "Yên Nhi", "Anh Khoa", "Bảo Ngọc",
             "Chiến Thắng", "Diệu Anh", "Em Dâu", "Phúc Lâm", "Gia Hân", "Hải Đăng",
             "Khải Vy"]

    for i in range(25):
        mode = modes[i % len(modes)]
        status = ConversationStatus.CLOSED if mode == ConversationMode.CLOSED else ConversationStatus.OPEN
        created = days_ago(rng.randint(0, 14))
        assigned = users[1 + (i % 2)].id if mode in (ConversationMode.HUMAN, ConversationMode.SEMI_AUTO) else None

        convos.append(Conversation(
            id=_uuid(),
            zalo_chat_id=f"zalo_conv_seed_{i:04d}",
            mode=mode,
            status=status,
            needs_human=mode in (ConversationMode.HUMAN, ConversationMode.SEMI_AUTO),
            version=1 + rng.randint(0, 2),
            assigned_recruiter_id=assigned,
            unread_count=rng.randint(0, 5) if mode != ConversationMode.CLOSED else 0,
            last_inbound_at=hours_ago(-rng.randint(-72, -1)),
            last_outbound_at=hours_ago(-rng.randint(1, 48)),
            created_at=created,
            updated_at=created + timedelta(hours=rng.randint(1, 72)),
        ))
    return convos


def make_messages_and_bot_runs(
    convos: list[Conversation],
    users: list[User],
) -> tuple[list[Message], list[BotRun]]:
    messages: list[Message] = []
    bot_runs: list[BotRun] = []

    # Realistic Vietnamese conversation templates
    candidate_openers = [
        "Xin chào, mình muốn hỏi về việc tuyển công nhân",
        "Cho mình hỏi nhà máy đang tuyển gì ạ?",
        "Mình nghe nói bên mình đang tuyển người, đúng không ạ?",
        "Xin chào, mình muốn ứng tuyển công nhân sản xuất",
        "Alo, mình muốn hỏi thông tin tuyển dụng ạ",
        "Cho mình hỏi lương bao nhiêu ạ?",
        "Nhà mình có bao ăn ở không ạ?",
        "Mình 25 tuổi, chưa có kinh nghiệm làm được không ạ?",
        "Xin hỏi xe đưa đón từ [tỉnh] đi mấy giờ ạ?",
        "Mình muốn biết thêm về công việc bên mình",
    ]

    bot_replies = [
        "Dạ chào bạn 👋 Mình là trợ lý tuyển dụng của VFIC. Bạn muốn tìm hiểu về công việc nào ạ?",
        "Dạ nhà máy đang tuyển công nhân sản xuất với mức lương 7-12 triệu. Bạn quan tâm đúng không ạ?",
        "Dạ có, nhà máy hỗ trợ bao ăn ở cho công nhân ngoại tỉnh. Ký túc xá đầy đủ tiện nghi ạ.",
        "Dạ xe đưa đón chạy từ 5h sáng. Mình gửi bạn lịch xe chi tiết nhé!",
        "Dạ bạn 25 tuổi hoàn toàn đáp ứng yêu cầu. Không cần kinh nghiệm, nhà máy sẽ đào tạo ạ.",
        "Dạ bảo hiểm đóng đầy đủ theo luật: BHXH, BHYT, BHTN ạ.",
        "Dạ thưởng tháng 13 và thưởng KPI hàng quý bạn nhé.",
        "Dạ bạn cho mình xin tên và số điện thoại để mình tạo hồ sơ nhé!",
    ]

    recruiter_replies = [
        "Chào anh/chị, em là Lan - tuyển dụng VFIC. Em hỗ trợ anh/chị ạ.",
        "Anh/chị gửi hồ sơ qua email cho em nhé. Em sẽ phản hồi trong 24h.",
        "Dạ, buổi interview dự kiến thứ 3 tuần sau anh/chị nhé.",
        "Em đã chuyển hồ sơ của anh/chị cho phòng nhân sự rồi ạ.",
    ]

    for i, conv in enumerate(convos):
        n_turns = rng.randint(2, 8)
        base_time = conv.created_at + timedelta(minutes=rng.randint(1, 30))

        for turn in range(n_turns):
            t = base_time + timedelta(minutes=turn * rng.randint(2, 60))

            if turn == 0:
                # Candidate opens
                sender = MessageSender.BOT  # inbound from Zalo appears as bot in our model
                body = candidate_openers[i % len(candidate_openers)]
                messages.append(Message(
                    conversation_id=conv.id,
                    sender=sender, body=body,
                    delivery_status=DeliveryStatus.SENT,
                    created_at=t,
                ))
            elif turn < n_turns - 1 and conv.mode == ConversationMode.BOT:
                # Bot replies
                run = BotRun(
                    conversation_id=conv.id,
                    started_at=t - timedelta(seconds=rng.randint(5, 30)),
                    ended_at=t,
                    version_at_start=conv.version,
                    proposed_reply=bot_replies[i % len(bot_replies)],
                    outcome=BotRunOutcome.SENT,
                )
                bot_runs.append(run)
                messages.append(Message(
                    conversation_id=conv.id,
                    sender=MessageSender.BOT,
                    body=run.proposed_reply,
                    bot_run_id=run.id,
                    delivery_status=DeliveryStatus.SENT,
                    created_at=t,
                ))
            elif conv.mode in (ConversationMode.HUMAN, ConversationMode.SEMI_AUTO):
                sender = MessageSender.RECRUITER
                body = recruiter_replies[i % len(recruiter_replies)]
                messages.append(Message(
                    conversation_id=conv.id,
                    sender=sender, body=body,
                    recruiter_id=conv.assigned_recruiter_id,
                    delivery_status=DeliveryStatus.SENT,
                    created_at=t,
                ))
                # Candidate follows up
                if turn < n_turns - 1:
                    messages.append(Message(
                        conversation_id=conv.id,
                        sender=MessageSender.BOT,  # Zalo inbound
                        body=rng.choice(["Dạ vâng ạ", "Ok em cảm ơn", "Mình sẽ suy nghĩ thêm",
                                         "Vâng, mình sẽ gửi hồ sơ", "Được ạ, mình muốn hỏi thêm về lương"]),
                        delivery_status=DeliveryStatus.SENT,
                        created_at=t + timedelta(minutes=rng.randint(1, 10)),
                    ))
            else:
                # Final bot reply
                body = bot_replies[(i + 3) % len(bot_replies)]
                run = BotRun(
                    conversation_id=conv.id,
                    started_at=t - timedelta(seconds=rng.randint(5, 20)),
                    ended_at=t,
                    version_at_start=conv.version,
                    proposed_reply=body,
                    outcome=BotRunOutcome.SENT,
                )
                bot_runs.append(run)
                messages.append(Message(
                    conversation_id=conv.id,
                    sender=MessageSender.BOT,
                    body=body,
                    bot_run_id=run.id,
                    delivery_status=DeliveryStatus.SENT,
                    created_at=t,
                ))

    return messages, bot_runs


def make_knowledge_documents(projects: list[Project]) -> list[KnowledgeDocument]:
    docs = [
        KnowledgeDocument(
            id=_uuid(), project_id=projects[0].id,
            file_name="lgd-faq.md", source="upload", status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# FAQ LG Display Hải Phòng\n\n## Lương\nMức lương từ 7-12 triệu tùy ca và vị trí...\n\n## Chỗ ở\nCó ký túc xá cho công nhân...",
            metadata_={"schema_version": "1", "type": "faq"},
            mime_type="text/markdown",
            digest_summary="FAQ tổng hợp về tuyển dụng LG Display Hải Phòng",
        ),
        KnowledgeDocument(
            id=_uuid(), project_id=projects[0].id,
            file_name="lgd-bus-timetable.md", source="upload", status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# Lịch xe bus đưa đón LG Display\n\n## Tuyến Hải Phòng\n5h15, 5h45, 13h00...",
            metadata_={"schema_version": "1", "type": "bus_timetable"},
            mime_type="text/markdown",
            digest_summary="Lịch xe đưa đón chi tiết cho công nhân LG Display",
        ),
        KnowledgeDocument(
            id=_uuid(), project_id=projects[1].id,
            file_name="lgd-bn-faq.md", source="upload", status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# FAQ LG Display Bắc Ninh\n\n## Mức lương\n7.5-13 triệu...\n\n## Phúc lợi\nHỗ trợ ăn ở, xe đưa đón...",
            metadata_={"schema_version": "1", "type": "faq"},
            mime_type="text/markdown",
            digest_summary="FAQ tuyển dụng LG Display Bắc Ninh",
        ),
        KnowledgeDocument(
            id=_uuid(), project_id=projects[2].id,
            file_name="samsung-bn-info.md", source="upload", status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# Thông tin tuyển dụng Samsung Bắc Ninh\n\n## Tổng quan\nKhu phức hợp sản xuất lớn nhất Samsung tại VN...",
            metadata_={"schema_version": "1", "type": "faq"},
            mime_type="text/markdown",
            digest_summary="Thông tin tổng quan tuyển dụng Samsung Bắc Ninh",
        ),
        KnowledgeDocument(
            id=_uuid(), project_id=projects[3].id,
            file_name="foxconn-na-info.md", source="upload", status=KnowledgeStatus.PUBLISHED,
            stage="PUBLISHED",
            raw_text="# Foxconn Nghệ An - Thông tin tuyển dụng\n\n## Tổng quan\nNhà máy sản xuất linh kiện điện tử...",
            metadata_={"schema_version": "1", "type": "faq"},
            mime_type="text/markdown",
            digest_summary="Thông tin tuyển dụng Foxconn Nghệ An",
        ),
        KnowledgeDocument(
            id=_uuid(), project_id=None,
            file_name="vfic-general-policy.md", source="upload", status=KnowledgeStatus.PUBLISHED,
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
        ("Lương cơ bản từ 7-12 triệu VNĐ/tháng tùy ca làm việc và vị trí. Ca 3 vòng lương 7-9 triệu, ca 4 lương 9-12 triệu.",
         "faq", {"topic": "lương"}),
        ("Nhà máy hỗ trợ bao ăn ở cho công nhân ngoại tỉnh. Ký túc xá 6 người/phòng, có điều hòa, nóng lạnh.",
         "faq", {"topic": "chỗ ở"}),
        ("Xe đưa đón miễn phí từ Hải Phòng, Thái Bình, Nam Định, Hà Nội. Lịch xe: 5h15, 5h45, 13h00 hàng ngày.",
         "faq", {"topic": "xe đưa đón"}),
        ("Đóng đầy đủ bảo hiểm xã hội, sức khỏe, thất nghiệp theo quy định pháp luật Việt Nam.",
         "faq", {"topic": "bảo hiểm"}),
        ("Thưởng tháng 13 hàng năm, thưởng KPI hàng quý. Cho phép làm thêm giờ với mức x1.5 - x2.",
         "faq", {"topic": "thưởng"}),
        ("Quy trình ứng tuyển: 1) Đăng ký qua Zalo 2) Phỏng vấn 3) Khám sức khỏe 4) Nhận việc trong 3-5 ngày.",
         "policy", {"topic": "quy trình"}),
        ("Thời gian thử việc 2 tháng, lương bằng 85% lương chính thức. Sau thử việc ký hợp đồng 12 tháng.",
         "policy", {"topic": "thử việc"}),
        ("Yêu cầu: tuổi 18-45, không yêu cầu kinh nghiệm cho công nhân sản xuất. Biết đọc viết, làm việc nhóm.",
         "faq", {"topic": "yêu cầu"}),
    ]

    for i, doc in enumerate(docs):
        # 2-3 chunks per document
        for j in range(rng.randint(2, 3)):
            spec = chunk_specs[(i * 3 + j) % len(chunk_specs)]
            chunks.append(KnowledgeChunk(
                id=_uuid(),
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
            ))
    return chunks


def make_audit_events(users: list[User]) -> list[AuditEvent]:
    events: list[AuditEvent] = []
    actions = [
        ("login", "user", None),
        ("create_user", "user", None),
        ("login", "user", None),
        ("publish_knowledge", "knowledge_document", None),
        ("login", "user", None),
        ("change_lead_stage", "lead", None),
        ("login", "user", None),
        ("takeover_conversation", "conversation", None),
        ("create_persona", "persona", None),
        ("login", "user", None),
        ("upload_knowledge", "knowledge_document", None),
        ("send_reply", "conversation", None),
        ("login", "user", None),
        ("change_lead_stage", "lead", None),
    ]
    for i, (action, target_type, _) in enumerate(actions):
        events.append(AuditEvent(
            actor_id=users[i % len(users)].id,
            action=action,
            target_type=target_type,
            payload={"ip": "127.0.0.1", "user_agent": "seed-script"},
            created_at=days_ago(rng.randint(0, 14)) + timedelta(hours=i),
        ))
    return events


# ---------------------------------------------------------------------------
# Main seed logic
# ---------------------------------------------------------------------------

# Tables to truncate in FK-safe order (leaf → root).
_TRUNCATE_ORDER = [
    "audit_events",
    "password_reset_otps",
    "job_feature_values",
    "worker_feature_catalog",
    "knowledge_chunks",
    "knowledge_documents",
    "follow_up_tasks",
    "lead_events",
    "leads",
    "messages",
    "bot_runs",
    "conversations",
    "jobs",
    "personas",
    "companies",
    "projects",
    "users",
]


def _truncate_all(engine) -> None:
    """Truncate every seeded table (leaf → root, respecting FKs)."""
    # Also handle tables that may exist but don't have ORM models.
    extra = ["memories", "message_dedup"]
    with Session(engine) as session:
        for table in _TRUNCATE_ORDER + extra:
            try:
                session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
            except Exception:  # noqa: BLE001
                pass  # table may not exist in this migration state
        session.commit()
    print("✓ truncated all seed tables")


def seed() -> None:
    settings = get_settings()
    url = settings.database_url_sync
    engine = create_engine(url)

    # 1. Wipe existing data
    _truncate_all(engine)

    with Session(engine) as db:
        # 2. Users
        users = make_users()
        db.add_all(users)
        db.flush()
        print(f"✓ {len(users)} users")

        # 3. Projects
        projects = make_projects()
        db.add_all(projects)
        db.flush()
        print(f"✓ {len(projects)} projects")

        # 4. Personas (before companies since companies don't FK persona, but projects may)
        personas = make_personas(users)
        db.add_all(personas)
        db.flush()
        print(f"✓ {len(personas)} personas")

        # 5. Companies
        companies = make_companies(projects)
        db.add_all(companies)
        db.flush()
        print(f"✓ {len(companies)} companies")

        # 6. Jobs
        jobs = make_jobs(companies)
        db.add_all(jobs)
        db.flush()
        print(f"✓ {len(jobs)} jobs")

        # 7. Worker Feature Catalog
        features = make_worker_features()
        db.add_all(features)
        db.flush()
        print(f"✓ {len(features)} worker features")

        # 8. Job Feature Values
        jfvs = make_job_feature_values(projects, features)
        db.add_all(jfvs)
        db.flush()
        print(f"✓ {len(jfvs)} job feature values")

        # 9. Conversations (must be before leads — leads.zalo_id FK → conversations.zalo_chat_id)
        convos = make_conversations(users)
        db.add_all(convos)
        db.flush()
        print(f"✓ {len(convos)} conversations")

        # 10. Leads (link first 25 to conversations via zalo_id)
        leads = make_leads(users, jobs, convos)
        db.add_all(leads)
        db.flush()
        print(f"✓ {len(leads)} leads")

        # 11. Lead Events
        lead_events = make_lead_events(leads, users)
        db.add_all(lead_events)
        db.flush()
        print(f"✓ {len(lead_events)} lead events")

        # 12. Follow-up Tasks
        tasks = make_followup_tasks(leads, users)
        db.add_all(tasks)
        db.flush()
        print(f"✓ {len(tasks)} follow-up tasks")

        # 13. Messages + Bot Runs
        msgs, runs = make_messages_and_bot_runs(convos, users)
        db.add_all(msgs)
        db.flush()
        print(f"✓ {len(msgs)} messages")
        db.add_all(runs)
        db.flush()
        print(f"✓ {len(runs)} bot runs")

        # 14. Knowledge Documents
        kdocs = make_knowledge_documents(projects)
        db.add_all(kdocs)
        db.flush()
        print(f"✓ {len(kdocs)} knowledge documents")

        # 15. Knowledge Chunks (raw SQL — embedding is vector(3072), not ORM-writable)
        kchunks = make_knowledge_chunks(kdocs)
        for chunk in kchunks:
            # Build SQL literals for complex types (psycopg text() can't adapt
            # dict/list/array). UUIDs as strings are fine since Postgres casts them.
            questions_arr = "{" + ",".join(
                q.replace("'", "''") for q in (chunk.questions or [])
            ) + "}"
            entities_json = json.dumps(chunk.entities or {}, ensure_ascii=False)
            proj = f"'{chunk.project_id}'" if chunk.project_id else "NULL"
            db.execute(text(
                f"INSERT INTO knowledge_chunks "
                f"(id, document_id, chunk_index, content, embedding, metadata, "
                f"project_id, source_quote, summary, questions, category, entities, "
                f"confidence, search_text) "
                f"VALUES ('{chunk.id}', '{chunk.document_id}', {chunk.chunk_index}, "
                f"'{chunk.content.replace(chr(39), chr(39)+chr(39))}', "
                f"NULL::vector(3072), '{{}}', "
                f"{proj}, "
                f"'{(chunk.source_quote or '').replace(chr(39), chr(39)+chr(39))}', "
                f"'{(chunk.summary or '').replace(chr(39), chr(39)+chr(39))}', "
                f"'{questions_arr}', "
                f"'{(chunk.category or '').replace(chr(39), chr(39)+chr(39))}', "
                f"'{entities_json}'::jsonb, "
                f"'{(chunk.confidence or '').replace(chr(39), chr(39)+chr(39))}', "
                f"'{(chunk.search_text or '').replace(chr(39), chr(39)+chr(39))}')"
            ))
        db.flush()
        print(f"✓ {len(kchunks)} knowledge chunks")

        # 16. Audit Events
        audit = make_audit_events(users)
        db.add_all(audit)
        db.flush()
        print(f"✓ {len(audit)} audit events")

        db.commit()
        print("\n✅ Dev database seeded successfully!")
        print(f"   Users: admin@vfic.dev / lan.nguyen@vfic.dev / minh.tran@vfic.dev")
        print(f"   Password: admin123")
        print(f"   35 leads, 25 conversations, {len(msgs)} messages across 4 projects")


if __name__ == "__main__":
    seed()
