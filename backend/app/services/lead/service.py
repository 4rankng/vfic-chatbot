"""Lead extraction + CRM service layer.

Business logic only — all raw SQL lives in ``repository.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, ConversationMode
from app.models.lead import FollowUpTask, FollowupStatus, Lead, LeadEvent, LeadStage
from app.models.user import Role, User
from app.prompts.lead_memory import LEAD_EXTRACT_SYSTEM_PROMPT
from app.services.audit_service import record_audit
from app.services.errors import ConflictError
from app.services.lead.events import LeadEventBus
from app.services.lead.normalizers import normalize_lead
from app.services.lead.repository import LeadRepository

Extractor = Callable[[str, str], Awaitable[str]]

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

_LEAD_STAGE_TITLES = {
    "NEW": "Mới",
    "CONTACTING": "Đang liên hệ",
    "REGISTERED": "Đã đăng ký",
    "SKIPPED": "Bỏ qua",
}


class LeadExtractionService:
    @staticmethod
    def user_turn(user_text: str, bot_output: str) -> str:
        return f"Tin nhắn người dùng: {user_text or ''}\n\nPhản hồi của bot: {bot_output or ''}"

    @staticmethod
    async def extract(
        extractor: Extractor, user_text: str, bot_output: str, chat_id: str
    ) -> dict | None:
        raw = await extractor(
            LEAD_EXTRACT_SYSTEM_PROMPT, LeadExtractionService.user_turn(user_text, bot_output)
        )
        return normalize_lead(raw, chat_id)

    @staticmethod
    async def upsert(db: AsyncSession, lead: dict) -> int | None:
        return await LeadRepository(db).upsert(lead)


class LeadService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = LeadRepository(db)
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
        needs_reply: bool = False,
        exclude_needs_reply: bool = False,
        zalo_id: str | None = None,
        zalo_ids: list[str] | None = None,
        q: str | None = None,
        sort_by: str | None = None,
        order: str | None = "desc",
        materialize: bool = True,
    ) -> tuple[list[Lead], int]:
        if materialize:
            await self.repo.materialize_conversation_leads(
                viewer.id if viewer.role != Role.admin else None
            )
        base = select(Lead)
        if viewer.role != Role.admin:
            base = base.where(
                or_(Lead.assigned_recruiter_id == viewer.id, Lead.assigned_recruiter_id.is_(None))
            )
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
        attention_condition = self._needs_reply_condition(viewer)
        if needs_reply:
            base = base.where(attention_condition)
        elif exclude_needs_reply:
            # Use IS NOT TRUE to avoid dropping rows where the OR yields NULL
            # (e.g. lead with next_action_at IS NULL and no matching branch).
            base = base.where(attention_condition.isnot(True))
        total = await self.db.scalar(select(func.count()).select_from(base.subquery()))
        sort_col = _LEAD_SORT.get((sort_by or "").lower()) or Lead.updated_at
        priority_order = case(
            (Lead.lead_score == "hot", 0),
            (Lead.lead_score == "warm", 1),
            else_=2,
        )
        attention_order = case(
            (self._unanswered_conversation_exists(viewer), 0),
            (self._due_followup_exists(), 1),
            (Lead.next_action_at <= func.now(), 1),
            (Lead.lead_score == "hot", 2),
            else_=3,
        )
        order_expr = sort_col.asc() if (order or "desc").lower() == "asc" else sort_col.desc()
        order_by = [priority_order.asc(), order_expr]
        if needs_reply:
            order_by = [attention_order.asc(), priority_order.asc(), order_expr]
        rows = (
            await self.db.scalars(
                base.order_by(*order_by).offset((page - 1) * per_page).limit(per_page)
            )
        ).all()
        return list(rows), int(total or 0)

    async def board(
        self,
        *,
        viewer: User,
        section_pages: dict[str, int],
        per_page: int = 25,
        q: str | None = None,
        sort_by: str | None = None,
        order: str | None = "desc",
    ) -> tuple[list[dict], int]:
        await self.repo.materialize_conversation_leads(
            viewer.id if viewer.role != Role.admin else None
        )
        sections: list[dict] = []
        configs: list[dict] = [
            {
                "key": "needs_reply",
                "title": "Cần trả lời",
                "is_priority": True,
                "kwargs": {"needs_reply": True},
            },
            *[
                {
                    "key": stage.value,
                    "title": _LEAD_STAGE_TITLES.get(stage.value, stage.value),
                    "is_priority": False,
                    "kwargs": {
                        "stage": stage,
                        "exclude_needs_reply": True,
                    },
                }
                for stage in LeadStage
            ],
        ]
        total = 0
        for config in configs:
            page = max(1, int(section_pages.get(config["key"], 1) or 1))
            rows, section_total = await self.list(
                viewer=viewer,
                page=page,
                per_page=per_page,
                q=q,
                sort_by=sort_by,
                order=order,
                materialize=False,
                **config["kwargs"],
            )
            total += section_total
            sections.append(
                {
                    "key": config["key"],
                    "title": config["title"],
                    "data": rows,
                    "total": section_total,
                    "page": page,
                    "per_page": per_page,
                    "is_priority": config["is_priority"],
                }
            )
        return sections, total

    async def update(self, lead: Lead, changes: dict) -> Lead:
        """Optimistic-concurrency update: rejects stale writes with ConflictError."""
        incoming_version = changes.pop("version", None)
        if incoming_version is not None:
            # Strip metadata fields that are not DB columns
            changes = {
                k: v
                for k, v in changes.items()
                if hasattr(lead, k) and k not in ("id", "created_at", "updated_at")
            }
            changes["version"] = Lead.version + 1
            if not await self.repo.optimistic_apply(lead.id, incoming_version, **changes):
                await self.db.refresh(lead)
                raise ConflictError("lead was modified by another recruiter")
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
        if not await self.repo.optimistic_apply(
            lead.id, lead.version, assigned_recruiter_id=recruiter_id, version=lead.version + 1
        ):
            await self.db.refresh(lead)
            raise ConflictError("lead was modified by another recruiter")
        await self.db.refresh(lead)
        self.db.add(
            LeadEvent(
                lead_id=lead.id,
                event_type="assign",
                payload={"recruiter_id": str(recruiter_id)},
                actor_id=actor.id,
            )
        )
        await record_audit(
            self.db,
            action="assign_lead",
            actor_id=actor.id,
            target_type="lead",
            target_id=str(lead.id),
            payload={"recruiter_id": str(recruiter_id)},
        )
        await self.db.commit()
        await self.db.refresh(lead)
        await self.events.lead_updated(lead, actor_name=actor.full_name)
        return lead

    async def set_stage(self, lead: Lead, stage: LeadStage, *, actor: User) -> Lead:
        prev = lead.lead_stage
        if not await self.repo.optimistic_apply(
            lead.id, lead.version, lead_stage=stage, version=lead.version + 1
        ):
            await self.db.refresh(lead)
            raise ConflictError("lead was modified by another recruiter")
        await self.db.refresh(lead)
        self.db.add(
            LeadEvent(
                lead_id=lead.id,
                event_type="stage_change",
                payload={"from": prev.value if prev else None, "to": stage.value},
                actor_id=actor.id,
            )
        )
        await record_audit(
            self.db,
            action="change_lead_stage",
            actor_id=actor.id,
            target_type="lead",
            target_id=str(lead.id),
            payload={"from": prev.value if prev else None, "to": stage.value},
        )
        await self.db.commit()
        await self.db.refresh(lead)
        await self.events.lead_updated(lead, actor_name=actor.full_name)
        return lead

    async def create_followup(
        self, lead: Lead, due_at: datetime, note: str | None, *, actor: User
    ) -> FollowUpTask:
        return await self.repo.create_followup(lead.id, due_at, note, created_by=actor.id)

    async def list_events(self, lead_id: int) -> list[LeadEvent]:
        return await self.repo.list_events(lead_id)

    async def list_followups(self, lead_id: int) -> list[FollowUpTask]:
        return await self.repo.list_followups(lead_id)

    # ── Private helpers ──────────────────────────────────────────────

    def _unanswered_conversation_exists(self, viewer: User):
        conditions = [
            Conversation.zalo_chat_id == Lead.zalo_id,
            Conversation.status == "OPEN",
            Conversation.mode.in_([ConversationMode.HUMAN, ConversationMode.SEMI_AUTO]),
            Conversation.last_inbound_at.is_not(None),
            or_(
                Conversation.last_outbound_at.is_(None),
                Conversation.last_inbound_at > Conversation.last_outbound_at,
            ),
        ]
        if viewer.role != Role.admin:
            conditions.append(
                or_(
                    Conversation.assigned_recruiter_id == viewer.id,
                    Conversation.assigned_recruiter_id.is_(None),
                )
            )
        return select(Conversation.id).where(*conditions).exists()

    def _due_followup_exists(self):
        return (
            select(FollowUpTask.id)
            .where(
                FollowUpTask.lead_id == Lead.id,
                FollowUpTask.status == FollowupStatus.PENDING,
                FollowUpTask.due_at <= func.now(),
            )
            .exists()
        )

    def _needs_reply_condition(self, viewer: User):
        not_skipped = Lead.lead_stage != LeadStage.SKIPPED
        return or_(
            and_(not_skipped, self._unanswered_conversation_exists(viewer)),
            and_(not_skipped, Lead.lead_score == "hot"),
            and_(not_skipped, Lead.next_action_at.isnot(None), Lead.next_action_at <= func.now()),
            and_(not_skipped, self._due_followup_exists()),
        )
