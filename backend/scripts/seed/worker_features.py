"""Worker-feature fixture: the answerable-benefit catalog and its per-project values."""

from __future__ import annotations

from app.models.company import Project
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog

from .common import new_uuid


def make_worker_features() -> list[WorkerFeatureCatalog]:
    features = [
        (
            "salary",
            "Mức lương",
            "Thu nhập",
            "Lương bao nhiêu ạ?",
            "Mức lương cơ bản và tổng thu nhập hàng tháng",
            0.95,
        ),
        (
            "accommodation",
            "Chỗ ở",
            "Phúc lợi",
            "Có bao ăn ở không ạ?",
            "Hỗ trợ chỗ ở cho công nhân xa nhà",
            0.90,
        ),
        (
            "transport",
            "Xe đưa đón",
            "Phúc lợi",
            "Có xe đưa đón không?",
            "Xe đưa đón từ các điểm tập kết",
            0.85,
        ),
        (
            "meal",
            "Bữa ăn",
            "Phúc lợi",
            "Có hỗ trợ ăn không ạ?",
            "Hỗ trợ bữa ăn trưa tại xưởng",
            0.80,
        ),
        (
            "insurance",
            "Bảo hiểm",
            "Phúc lợi",
            "Có đóng bảo hiểm không?",
            "Bảo hiểm xã hội, sức khỏe, thất nghiệp",
            0.85,
        ),
        (
            "shift",
            "Ca làm việc",
            "Thời gian",
            "Làm việc mấy ca ạ?",
            "Ca 2, ca 3 hoặc ca 4 tùy nhà máy",
            0.80,
        ),
        (
            "bonus",
            "Thưởng",
            "Thu nhập",
            "Có thưởng không ạ?",
            "Thưởng tháng 13, KPI, hiệu quả",
            0.70,
        ),
        (
            "overtime",
            "Làm thêm giờ",
            "Thời gian",
            "Có làm thêm giờ không?",
            "Cho phép làm thêm với mức lương x1.5",
            0.75,
        ),
        (
            "contract",
            "Hợp đồng",
            "Hành chính",
            "Ký hợp đồng kiểu gì ạ?",
            "Hợp đồng lao động theo luật Việt Nam",
            0.65,
        ),
        (
            "probation",
            "Thử việc",
            "Hành chính",
            "Thời gian thử việc bao lâu?",
            "Thường 1-2 tháng thử việc",
            0.60,
        ),
        (
            "training",
            "Đào tạo",
            "Phát triển",
            "Có đào tạo không ạ?",
            "Đào tạo tay nghề và an toàn lao động",
            0.55,
        ),
        (
            "uniform",
            "Đồng phục",
            "Khác",
            "Có cấp đồng phục không ạ?",
            "Cấp 2 bộ đồng phục/năm",
            0.40,
        ),
        (
            "contact_info",
            "Thông tin liên hệ",
            "Hành chính",
            "Làm sao để đăng ký ạ?",
            "Thông tin đăng ký và liên hệ nhà máy",
            0.70,
        ),
        (
            "bus_timetable",
            "Lịch xe bus",
            "Phúc lợi",
            "Xe bus mấy giờ chạy ạ?",
            "Lịch trình xe đưa đón chi tiết",
            0.90,
        ),
    ]
    return [
        WorkerFeatureCatalog(
            id=new_uuid(),
            feature_key=key,
            name_vi=name,
            category=cat,
            worker_question_vi=question,
            description=desc,
            default_importance_score=importance,
            is_active=True,
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
        "salary": (
            "7-12 triệu (tùy ca và kinh nghiệm)",
            {"min": 7, "max": 12, "unit": "triệu VNĐ"},
            0.95,
            True,
        ),
        "accommodation": (
            "Có bao ở — ký túc xá công nhân, 6 người/phòng",
            {"type": "ký túc xá", "capacity": "6 người/phòng"},
            0.90,
            True,
        ),
        "transport": (
            "Có xe đưa đón từ Hải Phòng, Thái Bình, Nam Định, Hà Nội",
            {"routes": ["HP", "TB", "ND", "HN"]},
            0.88,
            True,
        ),
        "meal": (
            "Hỗ trợ bữa ăn trưa tại nhà máy, 25.000 VNĐ/bữa",
            {"amount": 25000, "type": "ăn trưa"},
            0.80,
            False,
        ),
        "insurance": (
            "Đóng đầy đủ BHXH, BHYT, BHTN theo luật",
            {"types": ["BHXH", "BHYT", "BHTN"]},
            0.85,
            False,
        ),
        "shift": (
            "Ca 3 vòng: 6h-14h / 14h-22h / 22h-6h hoặc ca 4",
            {"types": ["ca 3", "ca 4"]},
            0.80,
            False,
        ),
        "bonus": (
            "Thưởng tháng 13, thưởng KPI hàng quý",
            {"types": ["tháng 13", "KPI"]},
            0.75,
            False,
        ),
        "overtime": (
            "Được làm thêm giờ, lương x1.5 ngày thường, x2 ngày lễ",
            {"rates": {"normal": 1.5, "holiday": 2.0}},
            0.70,
            False,
        ),
        "contract": (
            "HĐ 12 tháng, renew tự động. Thử việc 2 tháng = 85% lương",
            {"type": "12 tháng", "probation_rate": 0.85},
            0.65,
            False,
        ),
        "probation": (
            "2 tháng thử việc, lương bằng 85%",
            {"duration": "2 tháng", "rate": "85%"},
            0.60,
            False,
        ),
        "bus_timetable": (
            "Xe 5h15, 5h45, 13h00 từ Hải Phòng; 5h30, 6h00 từ Thái Bình",
            {},
            0.92,
            True,
        ),
    }
    for key, (val_text, val_json, strength, highlight) in lg_hp_vals.items():
        if key in feat_map:
            values.append(
                JobFeatureValue(
                    id=new_uuid(),
                    project_id=lg_hp,
                    feature_id=feat_map[key],
                    value_text=val_text,
                    value_json=val_json,
                    strength_score=strength,
                    display_priority=100 - values.__len__() % 10,
                    is_highlight=highlight,
                )
            )

    # LG Bắc Ninh
    lg_bn = projects[1].id
    lg_bn_vals = {
        "salary": (
            "7.5-13 triệu (ca 3: 8-10tr, ca ngày: 10-13tr)",
            {"min": 7.5, "max": 13},
            0.95,
            True,
        ),
        "accommodation": (
            "Hỗ trợ nhà ở 500.000 VNĐ/tháng cho người ngoại tỉnh",
            {"allowance": 500000},
            0.85,
            True,
        ),
        "transport": (
            "Xe đưa đón từ Hà Nội, Bắc Ninh, Bắc Giang, Thái Nguyên",
            {"routes": ["HN", "BN", "BG", "TN"]},
            0.88,
            True,
        ),
        "meal": ("Cấp 25.000 VNĐ ăn trưa, nhà máy có canteen", {"amount": 25000}, 0.80, False),
        "insurance": ("BHXH, BHYT, BHTN đầy đủ", {}, 0.85, False),
        "shift": ("Ca 3 vòng chính, mỗi ca 8 tiếng", {"types": ["ca 3"]}, 0.80, False),
        "bonus": ("Thưởng tháng 13 + thưởng hiệu quả sản xuất", {}, 0.75, False),
        "contract": ("HĐ 12 tháng, thử việc 60 ngày = 85%", {}, 0.65, False),
        "bus_timetable": ("Xe 5h00, 5h30, 6h00 từ các tỉnh, xe tăng vào mùa tuyển", {}, 0.90, True),
    }
    for key, (val_text, val_json, strength, highlight) in lg_bn_vals.items():
        if key in feat_map:
            values.append(
                JobFeatureValue(
                    id=new_uuid(),
                    project_id=lg_bn,
                    feature_id=feat_map[key],
                    value_text=val_text,
                    value_json=val_json,
                    strength_score=strength,
                    display_priority=100 - values.__len__() % 10,
                    is_highlight=highlight,
                )
            )

    # Samsung
    sam = projects[2].id
    sam_vals = {
        "salary": (
            "7-11 triệu + thưởng KPI 500k-1.5tr/tháng",
            {"min": 7, "max": 11, "bonus": "500k-1.5tr"},
            0.95,
            True,
        ),
        "accommodation": (
            "Bao ở — ký túc xá 4-6 người/phòng, có điều hòa",
            {"capacity": "4-6 người"},
            0.92,
            True,
        ),
        "transport": ("Xe đưa đón miễn phí từ 8 tỉnh", {}, 0.88, True),
        "meal": ("3 bữa/ngày, ăn tại canteen", {}, 0.82, True),
        "insurance": ("BHXH + BHYT + BHTN + Bảo hiểm tai nạn", {}, 0.85, False),
        "shift": ("Ca 3 vòng hoặc ca 2 vòng sáng-chiều", {}, 0.80, False),
        "bonus": ("Tháng 13 + thưởng sản xuất + thưởng chuyên cần", {}, 0.78, False),
        "contract": ("HĐ xác định thời hạn 1 năm, thử việc 2 tháng", {}, 0.65, False),
    }
    for key, (val_text, val_json, strength, highlight) in sam_vals.items():
        if key in feat_map:
            values.append(
                JobFeatureValue(
                    id=new_uuid(),
                    project_id=sam,
                    feature_id=feat_map[key],
                    value_text=val_text,
                    value_json=val_json,
                    strength_score=strength,
                    display_priority=100 - values.__len__() % 10,
                    is_highlight=highlight,
                )
            )

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
            values.append(
                JobFeatureValue(
                    id=new_uuid(),
                    project_id=fc,
                    feature_id=feat_map[key],
                    value_text=val_text,
                    value_json=val_json,
                    strength_score=strength,
                    display_priority=100 - values.__len__() % 10,
                    is_highlight=highlight,
                )
            )

    return values
