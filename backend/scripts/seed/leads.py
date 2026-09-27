"""Lead fixture: candidates, their stage events, and their follow-up tasks.

Also owns :func:`remove_trigger_generated_leads` — the conversation insert
trigger (Alembic 0025) creates a placeholder lead per thread, and the seed has
to drop those before inserting its own richer rows for the same ``zalo_id``.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.job import Job
from app.models.lead import FollowUpTask, FollowupStatus, Lead, LeadEvent, LeadScore, LeadStage
from app.models.user import User

from .common import days_ago, hours_ago, rng


def make_leads(users: list[User], jobs: list[Job], convos: list[Conversation]) -> list[Lead]:
    """Generate 35 leads across all stages with Vietnamese names.

    The first 25 leads link to the seeded conversations via zalo_id (FK to
    conversations.zalo_chat_id) and inherit that conversation's canonical
    contact_id, mirroring Alembic 0047's conversation→lead contact backfill and
    the contact-keyed lead trigger. Remaining 10 leads have zalo_id=None and
    contact_id=None (candidates who haven't chatted yet — e.g. inbound from
    other channels or manual entry).
    """
    first_names_m = [
        "Nguyễn Văn",
        "Trần Đức",
        "Phạm Hoàng",
        "Lê Quang",
        "Hoàng Minh",
        "Đặng Thanh",
        "Vũ Đình",
        "Bùi Xuân",
        "Đỗ Anh",
        "Lý Quốc",
        "Phan Thành",
        "Trịnh Duy",
        "Ngô Minh",
        "Huỳnh Quang",
        "Hà Văn",
    ]
    first_names_f = [
        "Nguyễn Thị",
        "Trần Thu",
        "Phạm Lan",
        "Lê Mai",
        "Hoàng Thu",
        "Đặng Hương",
        "Vũ Ngọc",
        "Bùi Thảo",
        "Đỗ Kim",
        "Lý Hoa",
        "Phan Tâm",
        "Trịnh Ánh",
        "Ngô Liên",
        "Huỳnh Nhung",
        "Hà Phương",
    ]
    last_names = [
        "An",
        "Bình",
        "Cường",
        "Dũng",
        "Em",
        "Phúc",
        "Giang",
        "Hải",
        "Khôi",
        "Linh",
        "Mai",
        "Nam",
        "Oanh",
        "Phong",
        "Quân",
        "Sơn",
        "Tâm",
        "Uyên",
        "Vinh",
        "Yến",
    ]
    living_areas = [
        "Hải Phòng",
        "Thái Bình",
        "Nam Định",
        "Hà Nội",
        "Bắc Ninh",
        "Bắc Giang",
        "Hải Dương",
        "Hưng Yên",
        "Vĩnh Phúc",
        "Quảng Ninh",
        "Nghệ An",
        "Hà Tĩnh",
        "Thanh Hóa",
        "Nghệ An",
        "Kon Tum",
    ]
    desired_jobs = [
        "Công nhân sản xuất",
        "Công nhân lắp ráp",
        "QC/KCS",
        "Công nhân đóng gói",
        "Kỹ thuật viên",
        "Công nhân SMT",
        "Công nhân kho vận",
    ]
    stages_weights = [
        (LeadStage.NEW, 8),
        (LeadStage.CONTACTING, 10),
        (LeadStage.REGISTERED, 9),
        (LeadStage.SKIPPED, 8),
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
        conv = convos[i % len(convos)] if i < len(convos) else None
        zalo_id = conv.zalo_chat_id if conv is not None else None
        created = days_ago(rng.randint(1, 30))

        score_map = {
            LeadStage.NEW: None,
            LeadStage.CONTACTING: LeadScore.warm,
            LeadStage.REGISTERED: LeadScore.hot,
            LeadStage.SKIPPED: LeadScore.not_interested,
        }

        lead = Lead(
            zalo_id=zalo_id,
            contact_id=conv.contact_id if conv is not None else None,
            name=full,
            phone=f"0{rng.randint(30, 79)}{rng.randint(1000000, 9999999)}" if i % 2 == 0 else None,
            age=rng.randint(19, 42),
            birth_year=1990 + rng.randint(-10, 10),
            living_area=living_areas[i % len(living_areas)],
            gender=gender,
            region=living_areas[i % len(living_areas)],
            desired_job=desired_jobs[i % len(desired_jobs)],
            years_experience=f"{rng.randint(0, 5)} năm"
            if rng.random() > 0.4
            else "Chưa có kinh nghiệm",
            expected_salary=f"{rng.randint(6, 12)} triệu" if rng.random() > 0.3 else None,
            lead_score=score_map[stage],
            lead_stage=stage,
            intent_score=round(rng.uniform(0.3, 1.0), 2) if stage == LeadStage.REGISTERED else None,
            qualification_reasons=["Đạt yêu cầu tuổi", "Có kinh nghiệm"]
            if stage == LeadStage.REGISTERED
            else [],
            assigned_recruiter_id=users[1 + (i % 2)].id
            if stage in (LeadStage.CONTACTING, LeadStage.REGISTERED)
            else None,
            notes=None,
            created_at=created,
            updated_at=created + timedelta(hours=rng.randint(1, 48)),
        )
        if stage == LeadStage.SKIPPED:
            lead.notes = "Bỏ qua: không phù hợp hoặc không liên lạc được"
        leads.append(lead)
    return leads


def make_lead_events(leads: list[Lead], users: list[User]) -> list[LeadEvent]:
    events: list[LeadEvent] = []
    event_types_by_stage: dict[LeadStage, list[str]] = {
        LeadStage.NEW: ["created", "auto_tag"],
        LeadStage.CONTACTING: ["created", "auto_tag", "first_contact", "followed_up"],
        LeadStage.REGISTERED: ["created", "auto_tag", "first_contact", "registered"],
        LeadStage.SKIPPED: ["created", "auto_tag", "skipped"],
    }

    for lead in leads:
        etypes = event_types_by_stage.get(lead.lead_stage, ["created"])
        for j, etype in enumerate(etypes):
            events.append(
                LeadEvent(
                    lead_id=lead.id,
                    event_type=etype,
                    payload={"source": "zalo", "note": f"{etype} event"},
                    actor_id=users[1].id if j > 0 else None,
                    created_at=lead.created_at + timedelta(hours=j),
                )
            )
    return events


def make_followup_tasks(leads: list[Lead], users: list[User]) -> list[FollowUpTask]:
    tasks: list[FollowUpTask] = []
    for i, lead in enumerate(leads):
        if lead.lead_stage in (LeadStage.CONTACTING, LeadStage.REGISTERED):
            tasks.append(
                FollowUpTask(
                    lead_id=lead.id,
                    due_at=hours_ago(-rng.randint(1, 72))
                    if lead.lead_stage == LeadStage.REGISTERED
                    else hours_ago(-rng.randint(-48, 24)),
                    note="Gọi lại hỏi tiến độ đăng ký"
                    if lead.lead_stage == LeadStage.REGISTERED
                    else "Liên hệ tư vấn chi tiết công việc",
                    status=rng.choice([FollowupStatus.PENDING, FollowupStatus.DONE]),
                    created_by=users[1 + (i % 2)].id,
                    completed_at=hours_ago(2) if rng.random() > 0.5 else None,
                )
            )
    return tasks


def remove_trigger_generated_leads(db: Session, convos: list[Conversation]) -> None:
    """Remove the conversation trigger's placeholder leads before seed inserts.

    Migration 0025 creates a lead for every newly inserted conversation. The
    deterministic seed then inserts its own richer lead record for the same
    `zalo_id`; remove only those trigger-generated placeholders first.
    """
    zalo_ids = [conv.zalo_chat_id for conv in convos]
    if zalo_ids:
        db.execute(delete(Lead).where(Lead.zalo_id.in_(zalo_ids)))
