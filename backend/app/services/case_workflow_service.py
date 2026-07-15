"""Validation and atomic publication of immutable case workflows."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.registry import CapabilityRegistry, get_capability_registry
from app.models.case_workflow import (
    CaseTagDefinition,
    CaseWorkflowStage,
    CaseWorkflowTransition,
    CaseWorkflowVersion,
)
from app.schemas.case_workflows import CaseWorkflowCreate
from app.services.audit_service import record_audit
from app.services.errors import ConflictError, NotFoundError
from app.services.installation.hashing import sha256_json


MAX_ATTRIBUTE_SCHEMA_BYTES = 16_384


class CaseWorkflowService:
    def __init__(self, db: AsyncSession, *, registry: CapabilityRegistry | None = None) -> None:
        self.db = db
        self.registry = registry or get_capability_registry()

    async def list(
        self, *, pack_key: str | None, workflow_key: str | None, page: int, per_page: int
    ) -> tuple[list[CaseWorkflowVersion], int]:
        filters = []
        if pack_key:
            filters.append(CaseWorkflowVersion.pack_key == pack_key)
        if workflow_key:
            filters.append(CaseWorkflowVersion.workflow_key == workflow_key)
        total = int(
            await self.db.scalar(
                select(func.count()).select_from(CaseWorkflowVersion).where(*filters)
            )
            or 0
        )
        rows = await self.db.scalars(
            select(CaseWorkflowVersion)
            .where(*filters)
            .order_by(CaseWorkflowVersion.created_at.desc(), CaseWorkflowVersion.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return list(rows), total

    async def get(
        self, version_id: uuid.UUID
    ) -> tuple[
        CaseWorkflowVersion,
        list[CaseWorkflowStage],
        list[CaseWorkflowTransition],
        list[CaseTagDefinition],
    ]:
        version = await self.db.get(CaseWorkflowVersion, version_id)
        if version is None:
            raise NotFoundError("case workflow not found")
        stages = list(
            await self.db.scalars(
                select(CaseWorkflowStage)
                .where(CaseWorkflowStage.workflow_version_id == version_id)
                .order_by(CaseWorkflowStage.position)
            )
        )
        transitions = list(
            await self.db.scalars(
                select(CaseWorkflowTransition)
                .where(CaseWorkflowTransition.workflow_version_id == version_id)
                .order_by(
                    CaseWorkflowTransition.from_stage_key, CaseWorkflowTransition.to_stage_key
                )
            )
        )
        tags = list(
            await self.db.scalars(
                select(CaseTagDefinition)
                .where(CaseTagDefinition.workflow_version_id == version_id)
                .order_by(CaseTagDefinition.position)
            )
        )
        return version, stages, transitions, tags

    async def create(self, body: CaseWorkflowCreate, actor_id: uuid.UUID) -> CaseWorkflowVersion:
        self._validate_definition(body)
        latest = await self.db.scalar(
            select(func.max(CaseWorkflowVersion.version_no)).where(
                CaseWorkflowVersion.pack_key == body.pack_key,
                CaseWorkflowVersion.workflow_key == body.workflow_key,
            )
        )
        previous = int(latest or 0)
        if body.expected_previous_version_no != (previous or None):
            raise ConflictError("workflow version changed since it was loaded")
        version_no = previous + 1
        payload = self.canonical_payload(body, version_no=version_no)
        version = CaseWorkflowVersion(
            pack_key=body.pack_key,
            workflow_key=body.workflow_key,
            version_no=version_no,
            label=body.label,
            schema_version=1,
            case_attribute_schema={
                key: value.model_dump(mode="json", exclude_none=True)
                for key, value in sorted(body.case_attribute_schema.items())
            },
            checksum=sha256_json(payload),
            created_by=actor_id,
        )
        self.db.add(version)
        try:
            await self.db.flush()
            self.db.add_all(
                [
                    CaseWorkflowStage(
                        workflow_version_id=version.id,
                        stage_key=item.key,
                        label=item.label,
                        position=item.position,
                        is_initial=item.is_initial,
                        is_terminal=item.is_terminal,
                    )
                    for item in body.stages
                ]
            )
            self.db.add_all(
                [
                    CaseWorkflowTransition(
                        workflow_version_id=version.id,
                        from_stage_key=item.from_stage_key,
                        to_stage_key=item.to_stage_key,
                    )
                    for item in body.transitions
                ]
            )
            self.db.add_all(
                [
                    CaseTagDefinition(
                        workflow_version_id=version.id,
                        tag_key=item.key,
                        label=item.label,
                        tone=item.tone,
                        position=item.position,
                    )
                    for item in body.tags
                ]
            )
            await record_audit(
                self.db,
                action="publish_case_workflow",
                actor_id=actor_id,
                target_type="case_workflow_version",
                target_id=str(version.id),
                payload={
                    "pack_key": version.pack_key,
                    "workflow_key": version.workflow_key,
                    "version_no": version.version_no,
                    "checksum": version.checksum,
                },
            )
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("workflow version was published concurrently") from exc
        await self.db.refresh(version)
        return version

    @staticmethod
    def canonical_payload(body: CaseWorkflowCreate, *, version_no: int) -> dict:
        return {
            "pack_key": body.pack_key,
            "workflow_key": body.workflow_key,
            "version_no": version_no,
            "label": body.label,
            "schema_version": 1,
            "stages": [
                item.model_dump(mode="json")
                for item in sorted(body.stages, key=lambda item: (item.position, item.key))
            ],
            "transitions": [
                item.model_dump(mode="json")
                for item in sorted(
                    body.transitions, key=lambda item: (item.from_stage_key, item.to_stage_key)
                )
            ],
            "tags": [
                item.model_dump(mode="json")
                for item in sorted(body.tags, key=lambda item: (item.position, item.key))
            ],
            "case_attribute_schema": {
                key: value.model_dump(mode="json", exclude_none=True)
                for key, value in sorted(body.case_attribute_schema.items())
            },
        }

    def _validate_definition(self, body: CaseWorkflowCreate) -> None:
        pack = self.registry.get_pack(body.pack_key)
        if body.workflow_key not in pack.workflow_ids:
            raise ValueError("workflow is not supported by the selected pack")
        keys = [item.key for item in body.stages]
        positions = [item.position for item in body.stages]
        if len(keys) != len(set(keys)) or len(positions) != len(set(positions)):
            raise ValueError("workflow stage keys and positions must be unique")
        initial = [item for item in body.stages if item.is_initial]
        if len(initial) != 1 or initial[0].is_terminal:
            raise ValueError("workflow requires one non-terminal initial stage")
        if not any(item.is_terminal for item in body.stages):
            raise ValueError("workflow requires at least one terminal stage")
        stage_by_key = {item.key: item for item in body.stages}
        transition_keys = [(item.from_stage_key, item.to_stage_key) for item in body.transitions]
        if len(transition_keys) != len(set(transition_keys)):
            raise ValueError("workflow transitions must be unique")
        for source, target in transition_keys:
            if source not in stage_by_key or target not in stage_by_key:
                raise ValueError("workflow transition endpoint does not exist")
            if source == target or stage_by_key[source].is_terminal:
                raise ValueError("terminal/self transitions are forbidden")
        reachable = {initial[0].key}
        changed = True
        while changed:
            changed = False
            for source, target in transition_keys:
                if source in reachable and target not in reachable:
                    reachable.add(target)
                    changed = True
        if reachable != set(keys):
            raise ValueError("every workflow stage must be reachable")
        tag_keys = [item.key for item in body.tags]
        tag_positions = [item.position for item in body.tags]
        if len(tag_keys) != len(set(tag_keys)) or len(tag_positions) != len(set(tag_positions)):
            raise ValueError("workflow tag keys and positions must be unique")
        encoded = json.dumps(
            {
                key: value.model_dump(mode="json", exclude_none=True)
                for key, value in body.case_attribute_schema.items()
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > MAX_ATTRIBUTE_SCHEMA_BYTES:
            raise ValueError("case attribute schema is too large")


def validate_case_attributes(schema: dict, attributes: dict) -> None:
    unknown = set(attributes) - set(schema)
    missing = {
        key for key, spec in schema.items() if spec.get("required") and key not in attributes
    }
    if unknown or missing:
        raise ValueError(
            f"case attributes violate closed schema; unknown={sorted(unknown)} missing={sorted(missing)}"
        )
    type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
    for key, value in attributes.items():
        spec = schema[key]
        kind = spec["type"]
        if kind in ("date", "datetime"):
            expected = str
        else:
            expected = type_map[kind]
        if not isinstance(value, expected) or (kind != "boolean" and isinstance(value, bool)):
            raise ValueError(f"case attribute {key} has invalid type")
        if kind == "date":
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"case attribute {key} has invalid date") from exc
        if kind == "datetime":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"case attribute {key} has invalid datetime") from exc
        if kind == "string" and spec.get("max_length") and len(value) > spec["max_length"]:
            raise ValueError(f"case attribute {key} is too long")
        if spec.get("enum") is not None and value not in spec["enum"]:
            raise ValueError(f"case attribute {key} is not an allowed value")
