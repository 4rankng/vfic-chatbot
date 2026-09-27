"""ChatOps assist + action orchestration for leads.

Extracted from ``LeadService``: the in-conversation assist panel builder
(:meth:`ChatopsService.build_assist`) and the recruiter quick-action mutator
(:meth:`ChatopsService.apply_action`). Unlike the pure view-model helpers in
:mod:`app.services.lead.viewmodels`, these compose LeadService operations
(stage changes, updates, conversation/message lookups), so ``ChatopsService`` is
constructed with the owning ``LeadService`` as a collaborator and reaches its
collaborators through it. ``LeadService`` forwards via thin delegates.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from app.models.conversation import MessageSender
from app.models.lead import Lead, LeadEvent, LeadScore, LeadStage
from app.models.user import User
from app.services.audit_service import record_audit
from app.services.lead import viewmodels as _vm_lib
from app.shared.domain.errors import ConflictError

if TYPE_CHECKING:
    from app.services.lead.service import LeadService

_CHATOPS_ACTIONS = {
    "mark_contacting",
    "schedule_followup",
    "mark_not_interested",
    "mark_registered",
}


class ChatopsService:
    def __init__(self, leads: LeadService) -> None:
        self.leads = leads

    async def build_assist(self, lead: Lead) -> dict:
        conversation = await self.leads._conversation_for_lead(lead)
        recent_messages = await self.leads._recent_messages(conversation)
        latest_worker = next(
            (msg for msg in reversed(recent_messages) if msg.sender == MessageSender.WORKER),
            None,
        )
        missing = _vm_lib.missing_fields(lead)
        return {
            "summary": _vm_lib.assist_summary(lead, latest_worker),
            "missing": missing,
            "reply": _vm_lib.suggested_reply(lead, missing),
            "next_action": _vm_lib.next_action(lead),
            "mode_label": _vm_lib.mode_label(conversation),
            "signals": _vm_lib.signals(lead, conversation),
            "recent_messages": [
                {
                    "sender": _vm_lib.message_sender_label(message.sender),
                    "body": message.body,
                    "created_at": message.created_at,
                }
                for message in recent_messages[-6:]
            ],
        }

    async def apply_action(self, lead: Lead, action: str, *, actor: User) -> Lead:
        if action not in _CHATOPS_ACTIONS:
            raise ValueError("unsupported ChatOps action")

        if action == "mark_contacting":
            if lead.lead_stage != LeadStage.CONTACTING:
                lead = await self.leads.set_stage(lead, LeadStage.CONTACTING, actor=actor)
        elif action == "mark_registered":
            if lead.lead_stage != LeadStage.REGISTERED:
                lead = await self.leads.set_stage(lead, LeadStage.REGISTERED, actor=actor)
        elif action == "mark_not_interested":
            lead = await self.leads.update(
                lead,
                {
                    "lead_score": LeadScore.not_interested,
                    "lead_stage": LeadStage.SKIPPED,
                    "notes": lead.notes or "Ứng viên không quan tâm.",
                },
            )
            conversation = await self.leads._conversation_for_lead(lead)
            if conversation is not None:
                conversation.followup_opted_out = True
        elif action == "schedule_followup":
            # Follow-up mornings live on the Vietnam business calendar — the
            # same calendar the dashboard's FOLLOWUP_TODAY counter mandates
            # (see _vn_today_predicate) — not 09:00 UTC (16:00 ICT).
            vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
            due_at = datetime.combine(
                datetime.now(vn_tz).date() + timedelta(days=1),
                time(hour=9, tzinfo=vn_tz),
            )
            await self.leads.repo.create_followup(
                lead.id,
                due_at,
                "Theo dõi lại từ màn hình chat.",
                created_by=actor.id,
            )
            if not await self.leads.repo.optimistic_apply(
                lead.id, lead.version, next_action_at=due_at, version=lead.version + 1
            ):
                await self.leads.db.refresh(lead)
                raise ConflictError("lead was modified by another recruiter")

        self.leads.db.add(
            LeadEvent(
                lead_id=lead.id,
                event_type="chatops_action",
                payload={"action": action},
                actor_id=actor.id,
            )
        )
        await record_audit(
            self.leads.db,
            action=f"lead_chatops_{action}",
            actor_id=actor.id,
            target_type="lead",
            target_id=str(lead.id),
            payload={"action": action},
        )
        await self.leads.db.commit()
        await self.leads.db.refresh(lead)
        await self.leads.events.lead_updated(lead, actor_name=actor.full_name)
        return lead
