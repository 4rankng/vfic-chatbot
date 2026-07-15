"""Generic case lifecycle with pinned workflow and optimistic mutations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import (
    Case,
    CaseFollowup,
    CaseLifecycle,
    CaseNote,
    CaseTagAssignment,
    FollowupStatus,
)
from app.models.case_workflow import (
    CaseTagDefinition,
    CaseWorkflowStage,
    CaseWorkflowTransition,
    CaseWorkflowVersion,
)
from app.models.contact import Contact
from app.models.user import Role, User
from app.schemas.cases import CaseCreate, CaseFollowupCreate, CaseUpdate
from app.services.audit_service import record_audit
from app.services.case_workflow_service import validate_case_attributes
from app.services.errors import ConflictError, ForbiddenError, NotFoundError
from app.services.contact_service import ContactService


class CaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _visible(user: User):
        return (
            True
            if user.role == Role.admin
            else or_(Case.assigned_user_id.is_(None), Case.assigned_user_id == user.id)
        )

    async def list(
        self,
        *,
        viewer: User,
        page: int,
        per_page: int,
        contact_id: uuid.UUID | None,
        stage: str | None,
        lifecycle: str | None,
        assignee_id: uuid.UUID | None,
        sort_by: str | None,
        order: str,
    ) -> tuple[list[Case], int]:
        query = select(Case).where(self._visible(viewer))
        for condition in (
            (Case.contact_id == contact_id) if contact_id else None,
            (Case.stage_key == stage) if stage else None,
            (Case.lifecycle == lifecycle) if lifecycle else None,
            (Case.assigned_user_id == assignee_id) if assignee_id else None,
        ):
            if condition is not None:
                query = query.where(condition)
        total = int(await self.db.scalar(select(func.count()).select_from(query.subquery())) or 0)
        columns = {
            "created_at": Case.created_at,
            "updated_at": Case.updated_at,
            "case_no": Case.case_no,
        }
        column = columns.get(sort_by or "updated_at", Case.updated_at)
        query = (
            query.order_by(column.asc() if order == "asc" else column.desc(), Case.id)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return list(await self.db.scalars(query)), total

    async def get_visible(self, case_id: uuid.UUID, viewer: User) -> Case:
        case = await self.db.scalar(select(Case).where(Case.id == case_id, self._visible(viewer)))
        if case is None:
            raise NotFoundError("case not found")
        return case

    async def list_projection(
        self, cases: list[Case]
    ) -> tuple[dict[uuid.UUID, list[str]], dict[uuid.UUID, CaseWorkflowVersion]]:
        if not cases:
            return {}, {}
        case_ids = [item.id for item in cases]
        tag_rows = await self.db.execute(
            select(CaseTagAssignment.case_id, CaseTagAssignment.tag_key)
            .where(CaseTagAssignment.case_id.in_(case_ids))
            .order_by(CaseTagAssignment.case_id, CaseTagAssignment.tag_key)
        )
        tags: dict[uuid.UUID, list[str]] = {}
        for case_id, tag_key in tag_rows:
            tags.setdefault(case_id, []).append(tag_key)
        workflow_ids = {item.workflow_version_id for item in cases}
        versions = await self.db.scalars(
            select(CaseWorkflowVersion).where(CaseWorkflowVersion.id.in_(workflow_ids))
        )
        return tags, {item.id: item for item in versions}

    async def create(self, body: CaseCreate, actor: User) -> Case:
        if actor.role == Role.admin:
            if await self.db.get(Contact, body.contact_id) is None:
                raise NotFoundError("contact not found")
        else:
            await ContactService(self.db).get_visible(body.contact_id, actor)
        workflow = await self.db.get(CaseWorkflowVersion, body.workflow_version_id)
        if workflow is None or workflow.checksum != body.workflow_checksum:
            raise ConflictError("workflow version/checksum does not match")
        validate_case_attributes(workflow.case_attribute_schema, body.attributes)
        initial = await self.db.scalar(
            select(CaseWorkflowStage).where(
                CaseWorkflowStage.workflow_version_id == workflow.id,
                CaseWorkflowStage.is_initial.is_(True),
            )
        )
        if initial is None or initial.is_terminal:
            raise ConflictError("workflow has no valid initial stage")
        if actor.role != Role.admin and body.assigned_user_id not in (None, actor.id):
            raise ForbiddenError("recruiters may assign a case only to themselves")
        await self._ensure_user(body.assigned_user_id)
        await ContactService(self.db).lock_visible_anchor(body.contact_id, actor)
        case = Case(
            contact_id=body.contact_id,
            workflow_version_id=workflow.id,
            workflow_checksum=workflow.checksum,
            stage_key=initial.stage_key,
            lifecycle=CaseLifecycle.OPEN.value,
            subject=body.subject,
            assigned_user_id=body.assigned_user_id,
            attributes=body.attributes,
        )
        self.db.add(case)
        await self.db.flush()
        await record_audit(
            self.db,
            action="create_case",
            actor_id=actor.id,
            target_type="case",
            target_id=str(case.id),
            payload={"workflow_version_id": str(workflow.id), "stage_key": initial.stage_key},
        )
        await self.db.commit()
        await self.db.refresh(case)
        return case

    async def update(self, case: Case, body: CaseUpdate, actor: User) -> Case:
        if case.lifecycle != CaseLifecycle.OPEN.value:
            raise ConflictError("closed or cancelled cases are immutable")
        values = body.model_dump(exclude={"version"}, exclude_unset=True, mode="python")
        if "attributes" in body.model_fields_set:
            workflow = await self.db.get(CaseWorkflowVersion, case.workflow_version_id)
            assert workflow is not None
            validate_case_attributes(workflow.case_attribute_schema, body.attributes)
        return await self._optimistic(case, body.version, actor, "update_case", values)

    async def assign(
        self, case: Case, *, assignee_id: uuid.UUID | None, version: int, actor: User
    ) -> Case:
        if case.lifecycle != CaseLifecycle.OPEN.value:
            raise ConflictError("closed or cancelled cases cannot be assigned")
        if actor.role != Role.admin:
            if case.assigned_user_id is not None or assignee_id != actor.id:
                raise ForbiddenError("recruiters may only claim unassigned cases")
        await self._ensure_user(assignee_id)
        return await self._optimistic(
            case, version, actor, "assign_case", {"assigned_user_id": assignee_id}
        )

    async def transition(self, case: Case, *, target: str, version: int, actor: User) -> Case:
        if case.lifecycle != CaseLifecycle.OPEN.value:
            raise ConflictError("closed or cancelled cases cannot transition")
        allowed = await self.db.scalar(
            select(
                exists().where(
                    CaseWorkflowTransition.workflow_version_id == case.workflow_version_id,
                    CaseWorkflowTransition.from_stage_key == case.stage_key,
                    CaseWorkflowTransition.to_stage_key == target,
                )
            )
        )
        if not allowed:
            raise ConflictError("case transition is not allowed")
        stage = await self.db.get(CaseWorkflowStage, (case.workflow_version_id, target))
        if stage is None:
            raise ConflictError("target stage does not exist")
        values: dict = {"stage_key": target}
        if stage.is_terminal:
            values.update(lifecycle=CaseLifecycle.CLOSED.value, closed_at=datetime.now(UTC))
        return await self._optimistic(case, version, actor, "transition_case", values)

    async def cancel(self, case: Case, *, version: int, actor: User) -> Case:
        if case.lifecycle != CaseLifecycle.OPEN.value:
            raise ConflictError("only open cases can be cancelled")
        return await self._optimistic(
            case,
            version,
            actor,
            "cancel_case",
            {"lifecycle": CaseLifecycle.CANCELLED.value, "closed_at": datetime.now(UTC)},
        )

    async def tags(self, case: Case) -> list[str]:
        return list(
            await self.db.scalars(
                select(CaseTagAssignment.tag_key)
                .where(CaseTagAssignment.case_id == case.id)
                .order_by(CaseTagAssignment.tag_key)
            )
        )

    async def replace_tags(
        self, case: Case, *, tag_keys: list[str], version: int, actor: User
    ) -> Case:
        await self._lock_visible(case.id, actor)
        if len(tag_keys) != len(set(tag_keys)):
            raise ConflictError("tag keys must be unique")
        valid = (
            set(
                await self.db.scalars(
                    select(CaseTagDefinition.tag_key).where(
                        CaseTagDefinition.workflow_version_id == case.workflow_version_id,
                        CaseTagDefinition.tag_key.in_(tag_keys),
                    )
                )
            )
            if tag_keys
            else set()
        )
        if valid != set(tag_keys):
            raise ConflictError("tag does not belong to the case workflow")
        claimed = await self.db.scalar(
            update(Case)
            .where(Case.id == case.id, Case.version == version)
            .values(version=Case.version + 1, updated_at=func.now())
            .returning(Case.id)
        )
        if claimed is None:
            raise ConflictError("case changed since it was loaded")
        await self.db.execute(delete(CaseTagAssignment).where(CaseTagAssignment.case_id == case.id))
        self.db.add_all(
            [
                CaseTagAssignment(
                    case_id=case.id,
                    workflow_version_id=case.workflow_version_id,
                    tag_key=key,
                    created_by=actor.id,
                )
                for key in tag_keys
            ]
        )
        await record_audit(
            self.db,
            action="replace_case_tags",
            actor_id=actor.id,
            target_type="case",
            target_id=str(case.id),
            payload={"tag_keys": sorted(tag_keys)},
        )
        await self.db.commit()
        await self.db.refresh(case)
        return case

    async def add_note(self, case: Case, *, body: str, actor: User) -> CaseNote:
        await self._lock_visible(case.id, actor)
        note = CaseNote(case_id=case.id, body=body, created_by=actor.id)
        self.db.add(note)
        await self.db.flush()
        await record_audit(
            self.db,
            action="create_case_note",
            actor_id=actor.id,
            target_type="case",
            target_id=str(case.id),
            payload={"note_id": note.id},
        )
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def notes(self, case: Case, *, limit: int) -> list[CaseNote]:
        return list(
            await self.db.scalars(
                select(CaseNote)
                .where(CaseNote.case_id == case.id)
                .order_by(CaseNote.created_at.desc(), CaseNote.id.desc())
                .limit(limit)
            )
        )

    async def add_followup(self, case: Case, body: CaseFollowupCreate, actor: User) -> CaseFollowup:
        await self._lock_visible(case.id, actor)
        if actor.role != Role.admin and body.assigned_user_id not in (None, actor.id):
            raise ForbiddenError("recruiters may assign follow-ups only to themselves")
        await self._ensure_user(body.assigned_user_id)
        followup = CaseFollowup(
            case_id=case.id, created_by=actor.id, **body.model_dump(mode="python")
        )
        self.db.add(followup)
        await self.db.flush()
        await record_audit(
            self.db,
            action="create_case_followup",
            actor_id=actor.id,
            target_type="case",
            target_id=str(case.id),
            payload={"followup_id": followup.id},
        )
        await self.db.commit()
        await self.db.refresh(followup)
        return followup

    async def followups(self, case: Case, *, limit: int) -> list[CaseFollowup]:
        return list(
            await self.db.scalars(
                select(CaseFollowup)
                .where(CaseFollowup.case_id == case.id)
                .order_by(CaseFollowup.created_at.desc(), CaseFollowup.id.desc())
                .limit(limit)
            )
        )

    async def finish_followup(
        self, case: Case, followup_id: int, *, version: int, status: FollowupStatus, actor: User
    ) -> CaseFollowup:
        await self._lock_visible(case.id, actor)
        values = {
            "status": status.value,
            "completed_at": datetime.now(UTC) if status == FollowupStatus.COMPLETED else None,
            "version": CaseFollowup.version + 1,
            "updated_at": func.now(),
        }
        result = await self.db.execute(
            update(CaseFollowup)
            .where(
                CaseFollowup.id == followup_id,
                CaseFollowup.case_id == case.id,
                CaseFollowup.version == version,
                CaseFollowup.status == FollowupStatus.PENDING.value,
            )
            .values(**values)
            .returning(CaseFollowup)
        )
        followup = result.scalar_one_or_none()
        if followup is None:
            raise ConflictError("follow-up changed or is no longer pending")
        await record_audit(
            self.db,
            action=f"{status.value.lower()}_case_followup",
            actor_id=actor.id,
            target_type="case",
            target_id=str(case.id),
            payload={"followup_id": followup_id},
        )
        await self.db.commit()
        return followup

    async def _optimistic(
        self, case: Case, version: int, actor: User, action: str, values: dict
    ) -> Case:
        result = await self.db.execute(
            update(Case)
            .where(Case.id == case.id, Case.version == version, self._visible(actor))
            .values(**values, version=Case.version + 1, updated_at=func.now())
            .returning(Case)
        )
        updated = result.scalar_one_or_none()
        if updated is None:
            still_visible = await self.db.scalar(
                select(exists().where(Case.id == case.id, self._visible(actor)))
            )
            if not still_visible:
                raise NotFoundError("case not found")
            raise ConflictError("case changed since it was loaded")
        await record_audit(
            self.db,
            action=action,
            actor_id=actor.id,
            target_type="case",
            target_id=str(case.id),
            payload={"fields": sorted(values)},
        )
        await self.db.commit()
        return updated

    async def _lock_visible(self, case_id: uuid.UUID, actor: User) -> Case:
        case = await self.db.scalar(
            select(Case)
            .where(Case.id == case_id, self._visible(actor))
            .with_for_update()
        )
        if case is None:
            raise NotFoundError("case not found")
        return case

    async def _ensure_user(self, user_id: uuid.UUID | None) -> None:
        if user_id is None:
            return
        locked_user_id = await self.db.scalar(
            select(User.id)
            .where(User.id == user_id)
            .with_for_update(read=True, key_share=True)
        )
        if locked_user_id is None:
            raise NotFoundError("assigned user not found")
