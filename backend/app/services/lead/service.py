"""Lead extraction + CRM service layer.

Business logic only — all raw SQL lives in ``repository.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
import re
import unicodedata

from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, ConversationMode, Message, MessageSender
from app.models.lead import FollowUpTask, FollowupStatus, Lead, LeadEvent, LeadScore, LeadStage
from app.models.user import Role, User
from app.services.audit_service import record_audit
from app.services.errors import ConflictError
from app.services.lead.events import LeadEventBus
from app.services.lead.repository import LeadRepository

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

_TAG_META: dict[str, dict[str, str | bool]] = {
    "has_phone": {"label": "Có SĐT", "tone": "good", "system": True},
    "missing_phone": {"label": "Thiếu SĐT", "tone": "warn", "system": True},
    "needs_follow_up": {"label": "Cần follow-up", "tone": "info", "system": False},
    "not_interested": {"label": "Không quan tâm", "tone": "danger", "system": False},
    "registered": {"label": "Đã đăng ký", "tone": "good", "system": False},
    "salary_missing": {"label": "Thiếu lương", "tone": "warn", "system": False},
    "location_missing": {"label": "Thiếu khu vực", "tone": "warn", "system": False},
    "needs_human": {"label": "Cần người xử lý", "tone": "danger", "system": False},
}

_MANUAL_TAG_KEYS = {key for key, meta in _TAG_META.items() if not bool(meta.get("system"))}
_SYSTEM_TAG_KEYS = {key for key, meta in _TAG_META.items() if bool(meta.get("system"))}

_CHATOPS_ACTIONS = {
    "mark_contacting",
    "schedule_followup",
    "mark_not_interested",
    "mark_registered",
}


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
            await self.db.commit()
            await self.db.refresh(lead)
            await self.events.lead_updated(lead)
            return lead
        # No version provided — trusted internal callers may apply direct updates.
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
        await self.db.commit()
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
        await self.db.commit()
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
        followup = await self.repo.create_followup(lead.id, due_at, note, created_by=actor.id)
        await self.db.commit()
        return followup

    async def list_operational_tags(self, lead: Lead) -> list[dict]:
        conversation = await self._conversation_for_lead(lead)
        manual = await self.repo.list_manual_tags(lead.id)
        payloads: list[dict] = []
        seen: set[str] = set()
        for key in self._system_tag_keys(lead, conversation):
            payloads.append(self._tag_payload(key, system=True))
            seen.add(key)
        for tag in manual:
            if tag.key in seen:
                continue
            payloads.append(
                {
                    "key": tag.key,
                    "label": tag.label,
                    "tone": tag.tone,
                    "system": False,
                }
            )
            seen.add(tag.key)
        return payloads

    async def replace_manual_tags(
        self,
        lead: Lead,
        keys: list[str],
        *,
        actor: User,
        tags: list[dict] | None = None,
    ) -> list[dict]:
        payloads = self._normalize_manual_tag_payloads(keys, tags or [])
        normalized = [payload["key"] for payload in payloads]
        await self.repo.replace_manual_tags(lead.id, payloads, created_by=actor.id)
        self.db.add(
            LeadEvent(
                lead_id=lead.id,
                event_type="tags_update",
                payload={"keys": normalized},
                actor_id=actor.id,
            )
        )
        await record_audit(
            self.db,
            action="update_lead_tags",
            actor_id=actor.id,
            target_type="lead",
            target_id=str(lead.id),
            payload={"keys": normalized},
        )
        await self.db.commit()
        await self.events.lead_updated(lead, actor_name=actor.full_name)
        return await self.list_operational_tags(lead)

    async def build_chatops_assist(self, lead: Lead) -> dict:
        conversation = await self._conversation_for_lead(lead)
        recent_messages = await self._recent_messages(conversation)
        latest_worker = next(
            (msg for msg in reversed(recent_messages) if msg.sender == MessageSender.WORKER),
            None,
        )
        missing = self._missing_fields(lead)
        mode_label = self._mode_label(conversation)
        summary = self._assist_summary(lead, latest_worker)
        reply = self._suggested_reply(lead, missing)
        next_action = self._next_action(lead)
        return {
            "summary": summary,
            "missing": missing,
            "reply": reply,
            "next_action": next_action,
            "mode_label": mode_label,
            "signals": self._signals(lead, conversation),
            "recent_messages": [
                {
                    "sender": self._message_sender_label(message.sender),
                    "body": message.body,
                    "created_at": message.created_at,
                }
                for message in recent_messages[-6:]
            ],
        }

    async def apply_chatops_action(self, lead: Lead, action: str, *, actor: User) -> Lead:
        if action not in _CHATOPS_ACTIONS:
            raise ValueError("unsupported ChatOps action")

        if action == "mark_contacting":
            if lead.lead_stage != LeadStage.CONTACTING:
                lead = await self.set_stage(lead, LeadStage.CONTACTING, actor=actor)
        elif action == "mark_registered":
            if lead.lead_stage != LeadStage.REGISTERED:
                lead = await self.set_stage(lead, LeadStage.REGISTERED, actor=actor)
        elif action == "mark_not_interested":
            lead = await self.update(
                lead,
                {
                    "lead_score": LeadScore.not_interested,
                    "lead_stage": LeadStage.SKIPPED,
                    "notes": lead.notes or "Ứng viên không quan tâm.",
                },
            )
            conversation = await self._conversation_for_lead(lead)
            if conversation is not None:
                conversation.followup_opted_out = True
        elif action == "schedule_followup":
            due_at = datetime.combine(
                datetime.now(timezone.utc).date() + timedelta(days=1),
                time(hour=9, tzinfo=timezone.utc),
            )
            await self.repo.create_followup(
                lead.id,
                due_at,
                "Theo dõi lại từ màn hình chat.",
                created_by=actor.id,
            )
            lead.next_action_at = due_at
            lead.updated_at = datetime.now(timezone.utc)
            lead.version += 1

        self.db.add(
            LeadEvent(
                lead_id=lead.id,
                event_type="chatops_action",
                payload={"action": action},
                actor_id=actor.id,
            )
        )
        await record_audit(
            self.db,
            action=f"lead_chatops_{action}",
            actor_id=actor.id,
            target_type="lead",
            target_id=str(lead.id),
            payload={"action": action},
        )
        await self.db.commit()
        await self.db.refresh(lead)
        await self.events.lead_updated(lead, actor_name=actor.full_name)
        return lead

    async def list_events(self, lead_id: int) -> list[LeadEvent]:
        return await self.repo.list_events(lead_id)

    async def list_followups(self, lead_id: int) -> list[FollowUpTask]:
        return await self.repo.list_followups(lead_id)

    # ── Private helpers ──────────────────────────────────────────────

    async def _conversation_for_lead(self, lead: Lead) -> Conversation | None:
        if not lead.zalo_id:
            return None
        return (
            await self.db.scalars(
                select(Conversation)
                .where(Conversation.zalo_chat_id == lead.zalo_id)
                .order_by(desc(Conversation.updated_at))
                .limit(1)
            )
        ).first()

    async def _recent_messages(self, conversation: Conversation | None) -> list[Message]:
        if conversation is None:
            return []
        rows = (
            await self.db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(desc(Message.created_at), desc(Message.id))
                .limit(12)
            )
        ).all()
        return list(reversed(rows))

    def _tag_payload(self, key: str, *, system: bool) -> dict:
        meta = _TAG_META[key]
        return {
            "key": key,
            "label": meta["label"],
            "tone": meta["tone"],
            "system": system,
        }

    def _system_tag_keys(self, lead: Lead, conversation: Conversation | None) -> list[str]:
        tags: list[str] = []
        tags.append("has_phone" if lead.phone and lead.phone.strip() else "missing_phone")
        if lead.next_action_at:
            tags.append("needs_follow_up")
        if lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED:
            tags.append("not_interested")
        if lead.lead_stage == LeadStage.REGISTERED:
            tags.append("registered")
        if not (lead.expected_salary and lead.expected_salary.strip()):
            tags.append("salary_missing")
        if not (lead.region and lead.region.strip()) and not (
            lead.living_area and lead.living_area.strip()
        ):
            tags.append("location_missing")
        if conversation is not None and (
            conversation.needs_human or conversation.mode == ConversationMode.HUMAN
        ):
            tags.append("needs_human")
        return tags

    def _normalize_manual_tag_keys(self, keys: list[str]) -> list[str]:
        return [payload["key"] for payload in self._normalize_manual_tag_payloads(keys, [])]

    def _normalize_manual_tag_payloads(
        self,
        keys: list[str],
        tags: list[dict],
    ) -> list[dict[str, str]]:
        normalized: list[str] = []
        payloads: list[dict[str, str]] = []
        seen: set[str] = set()

        def add(raw_key: str, raw_label: str | None = None, tone: str = "info") -> None:
            source = (raw_label or raw_key or "").strip()
            if not source:
                return
            key = self._normalize_manual_tag_key(raw_key or source)
            if not key or key in _SYSTEM_TAG_KEYS or key in seen:
                return
            if key in _MANUAL_TAG_KEYS:
                meta = _TAG_META[key]
                label = str(meta["label"])
                tag_tone = str(meta["tone"])
            else:
                label = source[:64]
                tag_tone = tone if tone in {"good", "warn", "danger", "info"} else "info"
            normalized.append(key)
            payloads.append({"key": key, "label": label, "tone": tag_tone})
            seen.add(key)

        for key in keys:
            add(key)

        for tag in tags:
            key = str(tag.get("key") or tag.get("label") or "")
            label = tag.get("label")
            if label is not None:
                label = str(label)
            add(key, label, str(tag.get("tone") or "info"))

        return payloads[:12]

    def _normalize_manual_tag_key(self, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if value in _TAG_META:
            return value
        if value.startswith("custom_") and re.fullmatch(r"custom_[a-z0-9_]{1,40}", value):
            return value
        vietnamese_safe = value.replace("đ", "d").replace("Đ", "D")
        ascii_value = (
            unicodedata.normalize("NFKD", vietnamese_safe)
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
        )
        key = re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")
        if not key:
            key = re.sub(r"\s+", "_", value.lower()).strip("_")
            key = re.sub(r"[^\w]+", "_", key).strip("_")
        if not key:
            return ""
        custom_key = f"custom_{key[:40]}"
        if custom_key in _SYSTEM_TAG_KEYS:
            return ""
        return custom_key

    def _missing_fields(self, lead: Lead) -> list[str]:
        missing: list[str] = []
        if not (lead.name and lead.name.strip()):
            missing.append("tên")
        if not (lead.phone and lead.phone.strip()):
            missing.append("số điện thoại")
        if not (lead.desired_job and lead.desired_job.strip()):
            missing.append("vị trí mong muốn")
        if not (lead.region and lead.region.strip()) and not (
            lead.living_area and lead.living_area.strip()
        ):
            missing.append("khu vực")
        if not (lead.expected_salary and lead.expected_salary.strip()):
            missing.append("mức lương mong muốn")
        return missing

    def _assist_summary(self, lead: Lead, latest_worker: Message | None) -> str:
        if lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED:
            return "Ứng viên đã thể hiện không quan tâm. Nên dừng nhắn chủ động trừ khi có tín hiệu mới."
        if latest_worker is not None:
            snippet = latest_worker.body.strip().replace("\n", " ")[:140]
            return f"Tin nhắn gần nhất của ứng viên: {snippet}"
        if lead.phone:
            return "Ứng viên đã có số điện thoại. Ưu tiên xác nhận nhu cầu, khu vực và chuyển sang bước đăng ký."
        return "Chưa có tin nhắn gần đây. Ưu tiên xin số điện thoại trước khi để bot tư vấn dài."

    def _suggested_reply(self, lead: Lead, missing: list[str]) -> str:
        if lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED:
            return "Cảm ơn bạn đã phản hồi. Nếu sau này bạn muốn tìm việc lại, mình luôn sẵn sàng hỗ trợ."
        if missing:
            fields = " và ".join(missing[:2])
            return f"Mình hỗ trợ bạn nhanh hơn nếu bạn cho mình {fields} nhé."
        return "Mình đã có đủ thông tin chính. Bạn muốn tư vấn viên gọi xác nhận hồ sơ không?"

    def _next_action(self, lead: Lead) -> str:
        if lead.next_action_at:
            return "Đã có lịch follow-up. Kiểm tra lại trước khi gửi thêm tin."
        if lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED:
            return "Dừng follow-up tự động và chỉ mở lại khi ứng viên chủ động phản hồi."
        if lead.phone:
            return "Đặt follow-up gần nhất và chuyển ứng viên sang Đang liên hệ."
        return "Xin số điện thoại, sau đó tạo follow-up nếu ứng viên phản hồi."

    def _mode_label(self, conversation: Conversation | None) -> str:
        if conversation is None:
            return "Chưa có hội thoại"
        if conversation.mode == ConversationMode.HUMAN:
            return "Người xử lý"
        if conversation.mode == ConversationMode.SEMI_AUTO:
            return "Bán tự động"
        if conversation.mode == ConversationMode.CLOSED:
            return "Đã đóng"
        return "Chatbot"

    def _message_sender_label(self, sender: MessageSender) -> str:
        if sender == MessageSender.WORKER:
            return "candidate"
        if sender == MessageSender.RECRUITER:
            return "recruiter"
        if sender == MessageSender.BOT:
            return "bot"
        return "system"

    def _signals(self, lead: Lead, conversation: Conversation | None) -> list[dict]:
        not_interested = (
            lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED
        )
        has_phone = bool(lead.phone and lead.phone.strip())
        needs_human = bool(
            conversation is not None
            and (conversation.needs_human or conversation.mode == ConversationMode.HUMAN)
        )
        return [
            {
                "key": "phone",
                "name": "Số điện thoại",
                "status": "Đã có thể liên hệ" if has_phone else "Chưa có dữ liệu",
                "active": has_phone,
                "action": "mark_contacting" if has_phone else None,
            },
            {
                "key": "not_interested",
                "name": "Không quan tâm",
                "status": "Nên dừng follow-up" if not_interested else "Chưa có tín hiệu",
                "active": not_interested,
                "action": "mark_not_interested" if not not_interested else None,
            },
            {
                "key": "followup",
                "name": "Follow-up",
                "status": "Đã có lịch" if lead.next_action_at else "Nên đặt lịch",
                "active": bool(lead.next_action_at),
                "action": None if lead.next_action_at else "schedule_followup",
            },
            {
                "key": "human",
                "name": "Cần người xử lý",
                "status": "Đang ưu tiên" if needs_human else "Theo dõi",
                "active": needs_human,
                "action": None,
            },
        ]

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
