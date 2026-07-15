"""Release-scoped execution of compiled ingestion templates.

The executor is deliberately deterministic in v1. It only turns declared
key/value aliases into evidence-backed generic facts; missing values are issues,
never invented defaults. Narrative chunks remain handled by the existing KB
pipeline.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion_template import (
    IngestionRunStatus,
    KBIngestionFileRun,
    KBIngestionRun,
    StructuredFact,
)
from app.models.knowledge import KBTextFile, KBVersion, KBVersionStatus
from app.models.provenance import ExtractionRun, FieldEvidence, SourceDocument, SourceFragment
from app.services.ingestion.extraction import extract_key_value_lines
from app.services.ingestion.template_compiler import compile_template
from app.services.ingestion.template_service import TemplateService
from app.services.audit_service import record_audit


class IngestionRunConflict(ValueError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class TemplateIngestionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def preview(
        self, definition: dict, source_text: str
    ) -> tuple[str, list[dict], list[dict]]:
        artifact, checksum = compile_template(definition)
        records, issues = self._extract_artifact(artifact, source_text, file_id=None)
        return checksum, records, issues

    async def start_run(self, version: KBVersion) -> KBIngestionRun:
        locked = await self.db.scalar(
            select(KBVersion).where(KBVersion.id == version.id).with_for_update()
        )
        if locked is None:
            raise IngestionRunConflict("KB version no longer exists")
        if locked.status in {KBVersionStatus.READY, KBVersionStatus.ACTIVE}:
            raise IngestionRunConflict(
                "READY or ACTIVE KB versions are immutable; create a new KB version"
            )
        if locked.template_version_id is None:
            raise IngestionRunConflict("KB version has no pinned template")
        files = list(
            (
                await self.db.scalars(
                    select(KBTextFile)
                    .where(KBTextFile.kb_version_id == locked.id)
                    .order_by(KBTextFile.id)
                )
            ).all()
        )
        template = await TemplateService(self.db).get_version(locked.template_version_id)
        if not template.compiled_artifact or not template.checksum:
            raise IngestionRunConflict("pinned template is not compiled")
        manifest = _sha(
            {
                "template_checksum": template.checksum,
                "compiler_version": template.compiler_version,
                "files": [{"id": str(item.id), "sha256": item.content_sha256} for item in files],
            }
        )
        active = await self.db.scalar(
            select(KBIngestionRun)
            .where(
                KBIngestionRun.kb_version_id == locked.id,
                KBIngestionRun.status.in_(
                    [
                        IngestionRunStatus.PENDING,
                        IngestionRunStatus.RUNNING,
                        IngestionRunStatus.REVIEW_REQUIRED,
                    ]
                ),
            )
            .order_by(KBIngestionRun.attempt_no.desc())
            .limit(1)
        )
        if active is not None:
            if active.manifest_sha256 != manifest:
                raise IngestionRunConflict(
                    "an active ingestion run has a different frozen manifest"
                )
            if active.status in {IngestionRunStatus.PENDING, IngestionRunStatus.RUNNING}:
                if active.lease_expires_at is None or active.lease_expires_at > datetime.now(UTC):
                    raise IngestionRunConflict("KB version already has an active ingestion run")
                active.status = IngestionRunStatus.FAILED
                active.finished_at = datetime.now(UTC)
                active.issues = [
                    *active.issues,
                    {
                        "severity": "warning",
                        "code": "lease_expired",
                        "message": "worker lease expired before completion",
                    },
                ]
            else:
                return active
        attempt_no = int(
            await self.db.scalar(
                select(func.coalesce(func.max(KBIngestionRun.attempt_no), 0) + 1).where(
                    KBIngestionRun.kb_version_id == locked.id
                )
            )
            or 1
        )
        run = KBIngestionRun(
            kb_version_id=locked.id,
            template_version_id=template.id,
            attempt_no=attempt_no,
            status=IngestionRunStatus.RUNNING,
            manifest_sha256=manifest,
            fencing_token=attempt_no,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=30),
            started_at=datetime.now(UTC),
        )
        locked.release_manifest_sha256 = manifest
        self.db.add(run)
        await self.db.flush()
        for item in files:
            self.db.add(KBIngestionFileRun(run_id=run.id, file_id=item.id))
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def materialize_version(
        self, version: KBVersion, *, run: KBIngestionRun | None = None
    ) -> KBIngestionRun:
        run = run or await self.start_run(version)
        if run.status == IngestionRunStatus.REVIEW_REQUIRED:
            return run
        if run.status != IngestionRunStatus.RUNNING:
            raise IngestionRunConflict("ingestion run is no longer active")
        if run.lease_expires_at is not None and run.lease_expires_at <= datetime.now(UTC):
            raise IngestionRunConflict("ingestion run lease expired")
        template = await TemplateService(self.db).get_version(run.template_version_id)
        artifact = template.compiled_artifact or {}
        template_family = await TemplateService(self.db).get_template(template.template_id)
        # The compatibility template intentionally delegates recruitment parsing
        # to the canonical pipeline until its typed adapter is fully migrated.
        if template_family.template_key == "recruitment_factory_builtin":
            run.status = IngestionRunStatus.READY
            run.finished_at = datetime.now(UTC)
            run.stats = {"facts": 0, "compatibility": "recruitment_builtin"}
            await self.db.commit()
            return run
        files = list(
            (
                await self.db.scalars(
                    select(KBTextFile).where(KBTextFile.kb_version_id == version.id)
                )
            ).all()
        )
        await self.db.execute(
            StructuredFact.__table__.delete().where(StructuredFact.kb_version_id == version.id)
        )
        all_issues: list[dict] = []
        fact_count = 0
        seen: set[tuple[str, str]] = set()
        for file in files:
            source_doc = await self._source_document(file, version)
            file_run = await self.db.scalar(
                select(KBIngestionFileRun).where(
                    KBIngestionFileRun.run_id == run.id, KBIngestionFileRun.file_id == file.id
                )
            )
            records, issues = self._extract_artifact(
                artifact, file.normalized_text, file_id=file.id
            )
            all_issues.extend([{**issue, "file_id": str(file.id)} for issue in issues])
            if file_run is not None:
                file_run.source_document_id = source_doc.id
                file_run.issues = issues
                file_run.status = "REVIEW_REQUIRED" if issues else "EXTRACTED"
            if any(issue["severity"] == "error" for issue in issues):
                continue
            extraction = ExtractionRun(
                source_document_id=source_doc.id,
                status="COMPLETED",
                extractor_version="template_executor_v1",
                schema_version="1",
                stats={"records": len(records)},
            )
            self.db.add(extraction)
            await self.db.flush()
            for record in records:
                key = (record["record_type_key"], record["natural_key_hash"])
                if key in seen:
                    all_issues.append(
                        {
                            "severity": "warning",
                            "code": "cross_file_conflict",
                            "message": "same natural key appears more than once in release",
                            "record_type_key": record["record_type_key"],
                        }
                    )
                    continue
                seen.add(key)
                evidence = await self._persist_evidence(extraction.id, source_doc.id, record)
                self.db.add(
                    StructuredFact(
                        project_id=version.project_id,
                        kb_version_id=version.id,
                        template_version_id=template.id,
                        run_id=run.id,
                        file_id=file.id,
                        record_type_key=record["record_type_key"],
                        source_mode=record["source_mode"],
                        natural_key=record["natural_key"],
                        natural_key_hash=record["natural_key_hash"],
                        payload=record["payload"],
                        evidence=evidence,
                        scope_type=record["scope_type"],
                        scope_id=record["scope_id"],
                    )
                )
                fact_count += 1
        requires_review = bool(all_issues)
        run.issues = all_issues
        run.stats = {"facts": fact_count, "files": len(files)}
        run.status = (
            IngestionRunStatus.REVIEW_REQUIRED if requires_review else IngestionRunStatus.READY
        )
        run.finished_at = datetime.now(UTC)
        version.status = (
            KBVersionStatus.REVIEW_REQUIRED if requires_review else KBVersionStatus.READY
        )
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def approve(
        self, run_id: uuid.UUID, *, reviewer_id: uuid.UUID, comment: str
    ) -> KBIngestionRun:
        run = await self.db.get(KBIngestionRun, run_id)
        if run is None or run.status != IngestionRunStatus.REVIEW_REQUIRED:
            raise IngestionRunConflict("only review-required runs can be approved")
        if any(issue.get("severity") == "error" for issue in run.issues):
            raise IngestionRunConflict("runs with validation errors must be corrected and rerun")
        run.status = IngestionRunStatus.READY
        run.reviewed_by = reviewer_id
        run.review_comment = comment
        version = await self.db.get(KBVersion, run.kb_version_id)
        if version is not None:
            version.status = KBVersionStatus.READY
        await record_audit(
            self.db,
            action="kb_ingestion_review_approved",
            actor_id=reviewer_id,
            target_type="kb_ingestion_run",
            target_id=str(run.id),
            payload={"comment": comment, "manifest": run.manifest_sha256},
        )
        await self.db.commit()
        return run

    async def reject(
        self, run_id: uuid.UUID, *, reviewer_id: uuid.UUID, comment: str
    ) -> KBIngestionRun:
        run = await self.db.get(KBIngestionRun, run_id)
        if run is None or run.status != IngestionRunStatus.REVIEW_REQUIRED:
            raise IngestionRunConflict("only review-required runs can be rejected")
        run.status = IngestionRunStatus.REJECTED
        run.reviewed_by = reviewer_id
        run.review_comment = comment
        version = await self.db.get(KBVersion, run.kb_version_id)
        if version is not None:
            version.status = KBVersionStatus.FAILED
            version.error_message = "Ingestion review rejected"
        await record_audit(
            self.db,
            action="kb_ingestion_review_rejected",
            actor_id=reviewer_id,
            target_type="kb_ingestion_run",
            target_id=str(run.id),
            payload={"comment": comment, "manifest": run.manifest_sha256},
        )
        await self.db.commit()
        return run

    async def _source_document(self, file: KBTextFile, version: KBVersion) -> SourceDocument:
        if file.source_document_id is not None:
            existing = await self.db.get(SourceDocument, file.source_document_id)
            if existing is not None:
                return existing
        source = await self.db.scalar(
            select(SourceDocument).where(
                SourceDocument.project_id == version.project_id,
                SourceDocument.sha256 == file.content_sha256,
            )
        )
        if source is None:
            source = SourceDocument(
                project_id=version.project_id,
                filename=file.filename,
                mime_type=file.mime_type,
                storage_uri=f"kbtextfile://{file.id}",
                sha256=file.content_sha256,
                status="NORMALIZED",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self.db.add(source)
            await self.db.flush()
        file.source_document_id = source.id
        return source

    async def _persist_evidence(
        self, extraction_run_id: int, source_document_id: int, record: dict
    ) -> dict:
        fragment = SourceFragment(
            document_id=source_document_id,
            block_type="key_value",
            block_order=0,
            original_text=record["source_text"],
            normalized_text=record["source_text"],
            created_at=datetime.now(UTC),
        )
        self.db.add(fragment)
        await self.db.flush()
        evidence: dict[str, int] = {}
        for field, value in record["payload"].items():
            if field not in record["evidence_fields"]:
                continue
            item = FieldEvidence(
                extraction_run_id=extraction_run_id,
                source_fragment_id=fragment.id,
                field_path=f"payload.{field}",
                value=str(value),
                extraction_method="template_key_value",
                confidence=1.0,
                created_at=datetime.now(UTC),
            )
            self.db.add(item)
            await self.db.flush()
            evidence[field] = item.id
        return {"field_evidence_ids": evidence, "source_fragment_id": fragment.id}

    def _extract_artifact(
        self, artifact: dict, source_text: str, *, file_id: uuid.UUID | None
    ) -> tuple[list[dict], list[dict]]:
        values = extract_key_value_lines(source_text)
        records: list[dict] = []
        issues: list[dict] = []
        for record_type in artifact.get("record_types", []):
            payload: dict[str, Any] = {}
            evidence_fields: set[str] = set()
            record_invalid = False
            found_any_source_value = False
            coercion_failed: set[str] = set()
            for field in record_type["fields"]:
                source_value = self._value_for_field(values, field)
                if source_value is None and field.get("constant") is not None:
                    source_value = field["constant"]
                if source_value is None:
                    continue
                found_any_source_value = True
                try:
                    payload[field["key"]] = self._coerce_value(source_value, field)
                except ValueError as exc:
                    issues.append(
                        {
                            "severity": "error",
                            "code": "invalid_field_type",
                            "message": f"{record_type['key']}.{field['key']}: {exc}",
                            "field_path": f"{record_type['key']}.{field['key']}",
                        }
                    )
                    record_invalid = True
                    coercion_failed.add(field["key"])
                    continue
                if field.get("constant") is None:
                    evidence_fields.add(field["key"])
            if not found_any_source_value:
                continue
            for field in record_type["fields"]:
                if (
                    field["required"]
                    and field["key"] not in payload
                    and field["key"] not in coercion_failed
                ):
                    issues.append(
                        {
                            "severity": "error",
                            "code": "missing_required_field",
                            "message": f"{record_type['key']}.{field['key']} has no source value",
                            "field_path": f"{record_type['key']}.{field['key']}",
                        }
                    )
                    record_invalid = True
            if not payload or record_invalid:
                continue
            missing_key = [key for key in record_type["natural_key_fields"] if key not in payload]
            if missing_key:
                issues.append(
                    {
                        "severity": "error",
                        "code": "missing_natural_key",
                        "message": f"{record_type['key']} missing natural-key fields",
                        "field_path": ",".join(missing_key),
                    }
                )
                continue
            natural_key = {key: payload[key] for key in record_type["natural_key_fields"]}
            source_modes = {
                field.get("source_mode", "sourced_fact")
                for field in record_type["fields"]
                if field["key"] in payload
            }
            if "narrative" in source_modes:
                continue
            scope_id_field = record_type.get("scope_id_field")
            # scope_id_field may point at an optional field that had no source
            # value and is therefore absent from payload; subscripting would
            # crash the whole ingestion run with an uncaught KeyError.
            scope_id = (
                str(payload[scope_id_field])
                if scope_id_field and scope_id_field in payload
                else None
            )
            records.append(
                {
                    "record_type_key": record_type["key"],
                    "source_mode": "derived" if source_modes == {"derived"} else "sourced_fact",
                    "natural_key": natural_key,
                    "natural_key_hash": _sha(natural_key),
                    "payload": payload,
                    "evidence_fields": evidence_fields,
                    "scope_type": record_type["scope_type"],
                    "scope_id": scope_id,
                    "source_text": source_text,
                }
            )
        return records, issues

    @staticmethod
    def _value_for_field(values: dict[str, str], field: dict) -> str | None:
        aliases = [field["key"], *field.get("aliases", [])]
        for alias in aliases:
            value = values.get(alias.strip().lower())
            if value:
                return value
        return None

    @staticmethod
    def _coerce_value(value: Any, field: dict) -> Any:
        value_type = field["type"]
        if value_type == "string":
            return str(value)
        if value_type == "number":
            return float(str(value).replace(",", ""))
        if value_type == "integer":
            return int(str(value).replace(",", ""))
        if value_type == "boolean":
            normalized = str(value).strip().lower()
            if normalized in {"true", "yes", "có", "co", "1"}:
                return True
            if normalized in {"false", "no", "không", "khong", "0"}:
                return False
            raise ValueError("must be a boolean")
        if value_type == "date":
            return date.fromisoformat(str(value)).isoformat()
        if value_type == "time":
            return time.fromisoformat(str(value)).isoformat()
        if value_type == "enum":
            if value not in field["enum_values"]:
                raise ValueError("must match an allowed enum value")
            return value
        raise ValueError("unsupported field type")
