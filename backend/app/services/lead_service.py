"""Lead extraction + CRM (port of VFIC Persist Lead + the CRM CRUD).

LeadExtractionService.normalise_* are a VERBATIM port of the n8n 'Merge Lead' code
node (phone/integer/lead_score normalisation). The upsert is COALESCE-based:
a non-empty existing value is never overwritten with null/empty (the live behavior).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import case, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.prompts.lead_memory import LEAD_EXTRACT_SYSTEM_PROMPT
from app.models.lead import FollowUpTask, Lead, LeadEvent, LeadStage
from app.models.user import Role, User
from app.services.audit_service import record_audit
from app.services.lead_events import LeadEventBus
from app.services.lead_repository import LeadRepository

Extractor = Callable[[str, str], Awaitable[str]]


class LeadConflict(Exception):
    """Raised when a lead update conflicts with a concurrent change (stale version)."""

    def __init__(self, message: str = "", owner_name: str | None = None) -> None:
        super().__init__(message)
        self.owner_name = owner_name


# --- pure normalisation (verbatim port of 'Merge Lead') ----------------------
def parse_lead_json(value) -> dict:
    if isinstance(value, dict):
        return value
    s = str(value if value is not None else "").strip()
    if not s:
        return {}
    s = re.sub(r"^\s*```(?:json)?", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"```\s*$", "", s, flags=re.IGNORECASE).strip()
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return {}
    try:
        parsed = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _pick(value) -> str | None:
    if value is None:
        return None
    t = re.sub(r"\s+", " ", str(value)).strip()
    return t or None


def normalize_phone(value) -> str | None:
    text = _pick(value)
    if not text:
        return None
    phone = re.sub(r"[^\d+]", "", text)
    if phone.startswith("+84"):
        phone = "0" + phone[3:]
    if phone.startswith("84") and len(phone) >= 11:
        phone = "0" + phone[2:]
    return phone if re.fullmatch(r"0\d{8,10}", phone) else None


def normalize_integer(value, min_v: int, max_v: int) -> int | None:
    text = _pick(value)
    if not text:
        return None
    m = re.search(r"\d{1,4}", text)
    if not m:
        return None
    n = int(m.group(0))
    if n < min_v or n > max_v:
        return None
    return n


def normalize_lead_score(value) -> str | None:
    """Return the LLM verdict verbatim; fall back to None (never guess).

    The old ``return "hot" if phone else None`` override was removed because it
    stamped every phone-bearing turn ``hot`` regardless of the LLM's warm /
    not_interested verdict, conflating "contactable" with "high intent".
    """
    score = (_pick(value) or "").lower()
    return score if score in ("hot", "warm", "not_interested") else None


def current_year() -> int:
    return datetime.now().year


def normalize_lead(raw, chat_id: str) -> dict | None:
    """Full port of 'Merge Lead': returns the normalised lead dict, or None if no chat_id."""
    chat_id = _pick(chat_id)
    if not chat_id:
        return None
    ext = parse_lead_json(raw)
    phone = normalize_phone(ext.get("phone"))

    # Route free-text miscellanea (notes + legacy latest_company) into ``notes``.
    _notes_parts: list[str] = []
    for key in ("notes", "latest_company"):  # latest_company kept for prompt-transition compat
        v = _pick(ext.get(key))
        if v:
            _notes_parts.append(v)
    notes = "; ".join(_notes_parts) if _notes_parts else None

    return {
        "zalo_id": chat_id,
        "name": _pick(ext.get("name")),
        "phone": phone,
        "birth_year": normalize_integer(ext.get("birth_year"), 1900, current_year()),
        "age": normalize_integer(ext.get("age"), 15, 80),
        "living_area": _pick(ext.get("living_area")),
        "address": _pick(ext.get("address")),
        "gender": _pick(ext.get("gender")),
        "region": _pick(ext.get("region")),
        "desired_job": _pick(ext.get("desired_job")),
        "years_experience": _pick(ext.get("years_experience")),
        "latest_company": None,  # pipeline no longer populates; column kept for backward-compat
        "expected_salary": _pick(ext.get("expected_salary")),
        "lead_score": normalize_lead_score(ext.get("lead_score")),
        "notes": notes,
    }


# Fields shown to the agent so it can see what's known and what's missing.
# Order matters: top = highest collection priority.  ``notes`` is passive
# capture (never probed directly — there is no natural "what are your notes?" question).
_PROFILE_FIELDS: list[tuple[str, str]] = [
    ("name", "Họ tên"),
    ("phone", "Số điện thoại"),
    ("desired_job", "Công việc mong muốn"),
    ("expected_salary", "Lương mong muốn"),
    ("region", "Tỉnh / thành"),
    ("living_area", "Khu vực sinh sống"),
    ("notes", "Ghi chú"),
]


def lead_profile_text(lead: dict | None) -> str:
    """Format a lead dict into a compact text block for injection into the agent context.

    Returns a 'THÔNG TIN ỨNG VIÊN' section showing known values and 'chưa có'
    for missing priority fields. Returns empty string when lead is None (new user).
    """
    if not lead:
        lines = [f"- {label}: chưa có" for _, label in _PROFILE_FIELDS]
        return "THÔNG TIN ỨNG VIÊN (mới, chưa có dữ liệu):\n" + "\n".join(lines)

    lines: list[str] = []
    for key, label in _PROFILE_FIELDS:
        val = _pick(lead.get(key))
        lines.append(f"- {label}: {val or 'chưa có'}")
    return "THÔNG TIN ỨNG VIÊN:\n" + "\n".join(lines)


# Whitelist of sortable lead columns. Unknown / absent sort keys fall back to
# updated_at (the default inbox ordering). Keys are lower-cased to match the
# dataProvider which upper-cases the order dir but leaves the field as-is.
_LEAD_SORT = {
    "updated_at": Lead.updated_at,
    "created_at": Lead.created_at,
    "name": Lead.name,
    "lead_stage": Lead.lead_stage,
    "lead_score": Lead.lead_score,
}


class LeadExtractionService:
    @staticmethod
    def user_turn(user_text: str, bot_output: str) -> str:
        return f"Tin nhắn người dùng: {user_text or ''}\n\nPhản hồi của bot: {bot_output or ''}"

    @staticmethod
    async def extract(extractor: Extractor, user_text: str, bot_output: str, chat_id: str) -> dict | None:
        raw = await extractor(LEAD_EXTRACT_SYSTEM_PROMPT, LeadExtractionService.user_turn(user_text, bot_output))
        return normalize_lead(raw, chat_id)

    @staticmethod
    async def upsert(db: AsyncSession, lead: dict) -> int | None:
        return await LeadRepository(db).upsert(lead)


class LeadService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.events = LeadEventBus()

    async def get(self, lead_id: int) -> Lead | None:
        return await self.db.get(Lead, lead_id)

    async def list(
        self,
        *,
        viewer: User,
        page: int = 1,
        per_page: int = 25,
        stage: LeadStage | None = None,
        zalo_id: str | None = None,
        zalo_ids: list[str] | None = None,
        q: str | None = None,
        sort_by: str | None = None,
        order: str | None = "desc",
    ) -> tuple[list[Lead], int]:
        base = select(Lead)
        if viewer.role != Role.admin:
            base = base.where(or_(Lead.assigned_recruiter_id == viewer.id, Lead.assigned_recruiter_id.is_(None)))
        if stage is not None:
            base = base.where(Lead.lead_stage == stage)
        if zalo_id:
            base = base.where(Lead.zalo_id == zalo_id)
        if zalo_ids:
            base = base.where(Lead.zalo_id.in_(zalo_ids))
        if q:
            pat = f"%{q}%"
            ua = func.extensions.unaccent
            base = base.where(
                or_(
                    ua(Lead.name).ilike(ua(pat)),
                    ua(Lead.phone).ilike(ua(pat)),
                    ua(Lead.desired_job).ilike(ua(pat)),
                    ua(Lead.zalo_id).ilike(ua(pat)),
                )
            )
        total = await self.db.scalar(select(func.count()).select_from(base.subquery()))
        sort_col = _LEAD_SORT.get((sort_by or "").lower()) or Lead.updated_at
        priority_order = case(
            (Lead.lead_score == "hot", 0),
            (Lead.lead_score == "warm", 1),
            else_=2,
        )
        order_expr = sort_col.asc() if (order or "desc").lower() == "asc" else sort_col.desc()
        rows = (
            await self.db.scalars(
                base.order_by(priority_order.asc(), order_expr)
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
        return list(rows), int(total or 0)

    async def update(self, lead: Lead, changes: dict) -> Lead:
        """Optimistic-concurrency update: rejects stale writes with LeadConflict."""
        incoming_version = changes.pop("version", None)
        if incoming_version is not None:
            # Strip metadata fields that are not DB columns
            changes = {k: v for k, v in changes.items() if hasattr(lead, k) and k not in ("id", "created_at", "updated_at")}
            changes["version"] = Lead.version + 1
            res = await self.db.execute(
                update(Lead)
                .where(
                    Lead.id == lead.id,
                    Lead.version == incoming_version,
                )
                .values(**changes, updated_at=func.now())
                .execution_options(synchronize_session=False)
            )
            await self.db.commit()
            if res.rowcount == 0:
                await self.db.refresh(lead)
                raise LeadConflict("lead was modified by another recruiter")
            await self.db.refresh(lead)
            await self.events.lead_updated(lead)
            return lead
        # No version provided — apply directly (backward compat for internal callers)
        for k, v in changes.items():
            if hasattr(lead, k) and k not in ("id", "created_at", "updated_at"):
                setattr(lead, k, v)
        await self.db.commit()
        await self.db.refresh(lead)
        await self.events.lead_updated(lead)
        return lead

    async def assign(self, lead: Lead, recruiter_id: uuid.UUID, *, actor: User) -> Lead:
        res = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead.id,
                Lead.version == lead.version,
            )
            .values(
                assigned_recruiter_id=recruiter_id,
                version=Lead.version + 1,
                updated_at=func.now(),
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if res.rowcount == 0:
            await self.db.refresh(lead)
            raise LeadConflict("lead was modified by another recruiter")
        await self.db.refresh(lead)
        self.db.add(LeadEvent(lead_id=lead.id, event_type="assign", payload={"recruiter_id": str(recruiter_id)}, actor_id=actor.id))
        await record_audit(self.db, action="assign_lead", actor_id=actor.id, target_type="lead", target_id=str(lead.id), payload={"recruiter_id": str(recruiter_id)})
        await self.db.commit()
        await self.db.refresh(lead)
        await self.events.lead_updated(lead, actor_name=actor.full_name)
        return lead

    async def set_stage(self, lead: Lead, stage: LeadStage, *, actor: User) -> Lead:
        prev = lead.lead_stage
        res = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead.id,
                Lead.version == lead.version,
            )
            .values(
                lead_stage=stage,
                version=Lead.version + 1,
                updated_at=func.now(),
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if res.rowcount == 0:
            await self.db.refresh(lead)
            raise LeadConflict("lead was modified by another recruiter")
        await self.db.refresh(lead)
        self.db.add(LeadEvent(lead_id=lead.id, event_type="stage_change", payload={"from": prev.value if prev else None, "to": stage.value}, actor_id=actor.id))
        await record_audit(self.db, action="change_lead_stage", actor_id=actor.id, target_type="lead", target_id=str(lead.id), payload={"from": prev.value if prev else None, "to": stage.value})
        await self.db.commit()
        await self.db.refresh(lead)
        await self.events.lead_updated(lead, actor_name=actor.full_name)
        return lead

    async def create_followup(self, lead: Lead, due_at: datetime, note: str | None, *, actor: User) -> FollowUpTask:
        fu = FollowUpTask(lead_id=lead.id, due_at=due_at, note=note, created_by=actor.id)
        self.db.add(fu)
        await self.db.commit()
        await self.db.refresh(fu)
        return fu

    async def list_events(self, lead_id: int) -> list[LeadEvent]:
        return list((await self.db.scalars(select(LeadEvent).where(LeadEvent.lead_id == lead_id).order_by(desc(LeadEvent.created_at)))).all())

    async def list_followups(self, lead_id: int) -> list[FollowUpTask]:
        return list((await self.db.scalars(select(FollowUpTask).where(FollowUpTask.lead_id == lead_id).order_by(FollowUpTask.due_at))).all())
