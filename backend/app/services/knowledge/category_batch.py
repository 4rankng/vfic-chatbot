"""Prepare a source's categories durably, then publish their pointers together."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select


from app.models.knowledge import (
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.services.audit_service import record_audit
from app.services.knowledge.category_authority import category_projection_allowed, locked_project
from app.services.knowledge.category_contracts import (
    category_checksum,
    validate_category_payload,
)
from app.project_knowledge.domain.legacy_job_references import (
    strip_legacy_job_reference_source,
)
from app.services.knowledge.category_markdown import (
    build_source_markdown,
    parse_category_markdown,
)
from app.services.knowledge.category_projections import render_category_units
from app.services.knowledge.category_service import (
    MAX_CATEGORY_PROCESSING_ATTEMPTS,
    CategoryActivationError,
    _ensure_category_rows,
)
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo
from app.services.knowledge.training_features import (
    auto_training_feature_intent_current,
    category_snapshot,
    feature_publication_state,
    publish_training_features,
    same_feature_intent,
    snapshot_feature_values,
)
from app.services.knowledge.retrieval_selftest import (
    RetrievalSelftestError,
    _record_list_field,
    _selftest_query,
    retrieval_selftest_failures,
)
from app.services.knowledge.training_guard import ensure_training_owner
from app.shared.domain.errors import ConflictError

# When the retrieval self-test rejects a record's label, the LLM gets this
# many bounded rounds to rewrite the offending field before the batch fails
# with the real error. Authoring is the LLM's job; the gate stays.
SELFTEST_REPAIR_MAX_ATTEMPTS = 2

_SELFTEST_FAILURE_QUERY_RE = re.compile(r'^"(.*)" would not retrieve its own record')


def _repair_prompt(record: dict, field: str, content: str) -> tuple[str, str]:
    system = (
        "Bạn sửa nhãn của một bản ghi kiến thức tuyển dụng để nhãn tự truy vấn "
        "được nội dung của chính bản ghi đó. Chỉ viết lại đúng MỘT trường được "
        "chỉ định, dùng các sự kiện đã có trong bản ghi và nội dung; tuyệt đối "
        "không bịa số tiền, số điện thoại, địa điểm hay điều kiện mới. Trả về "
        "đúng một JSON object."
    )
    user = json.dumps(
        {
            "record": record,
            "field_to_rewrite": field,
            "record_content": content[:1200],
            "required_output": {
                field: "nhãn mới bằng tiếng Việt, cụ thể, ít nhất 5 chữ cái",
            },
        },
        ensure_ascii=False,
    )
    return system, user


def _parse_repair_value(raw: str, field: str) -> str | None:
    """Extract the rewritten field from the LLM's reply; None when unusable."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    value = payload.get(field) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


async def repair_selftest_records(document, units, failures, llm_json) -> bool:
    """Rewrite each self-test-offending record's query-like field via the LLM.

    The failure messages quote the exact query string, which is the record's
    ``question``/``title``/``name`` value — that is how offending records are
    located. Records are replaced with validated copies; True means the
    document changed and the caller must re-render, re-embed and re-test.
    Unusable LLM output leaves the record untouched so the real failure
    stands.
    """
    list_field = _record_list_field(document)
    if list_field is None or llm_json is None:
        return False
    records = getattr(document, list_field)
    offending = {
        match.group(1)
        for failure in failures
        if (match := _SELFTEST_FAILURE_QUERY_RE.match(failure))
    }
    changed = False
    for index, record in enumerate(records):
        payload = record.model_dump(mode="json", exclude_none=True)
        query_field = _selftest_query(payload)
        if query_field is None or query_field[0] not in offending:
            continue
        field, current = query_field[1], query_field[0]
        system, user = _repair_prompt(payload, field, units[index]["content"])
        try:
            raw = await llm_json(system, user)
            repaired = _parse_repair_value(raw, field)
        except Exception:  # noqa: BLE001 — a broken provider must not sink the batch
            continue
        if not repaired or repaired == current or len(repaired) > 200:
            continue
        records[index] = record.model_copy(update={field: repaired})
        changed = True
    return changed


async def _locked_category_state(db, project_id):
    rows = list((await db.scalars(
        select(KnowledgeCategory)
        .where(KnowledgeCategory.project_id == project_id)
        .order_by(KnowledgeCategory.category_key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).all())
    latest = dict((await db.execute(
        select(
            KnowledgeCategoryRevision.category_id,
            func.max(KnowledgeCategoryRevision.revision_no),
        )
        .where(KnowledgeCategoryRevision.category_id.in_([row.id for row in rows]))
        .group_by(KnowledgeCategoryRevision.category_id)
    )).all())
    return rows, latest


async def capture_training_baseline(db, project_id):
    """Capture category intent while upload holds the project's write lock."""
    await _ensure_category_rows(db, project_id)
    rows, latest = await _locked_category_state(db, project_id)
    return category_snapshot(rows, latest)


async def training_source_reusable(db, doc) -> bool:
    """An identical file is a retry only while its category intent is current."""
    training = (doc.metadata_ or {}).get("project_training", {})
    progress = (doc.digest_meta or {}).get("project_training", {})
    if (doc.digest_meta or {}).get("features", {}).get("status") == "SUPERSEDED":
        return False
    if not await auto_training_feature_intent_current(db, doc):
        return False
    completed = progress.get("status") == "COMPLETED"
    expected = (
        training.get("published_snapshot")
        if completed or training.get("published_snapshot")
        else training.get("batch_snapshot") or training.get("extraction_baseline")
    )
    if expected is None and not (doc.digest_meta or {}).get("project_training", {}).get(
        "completed"
    ):
        return True  # No category work has been staged yet.
    rows = list(
        (
            await db.scalars(
                select(KnowledgeCategory)
                .where(KnowledgeCategory.project_id == doc.project_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    latest = dict(
        (
            await db.execute(
                select(
                    KnowledgeCategoryRevision.category_id,
                    func.max(KnowledgeCategoryRevision.revision_no),
                )
                .where(KnowledgeCategoryRevision.category_id.in_([row.id for row in rows]))
                .group_by(KnowledgeCategoryRevision.category_id)
            )
        ).all()
    )
    if expected is not None:
        if TrainingCategoryBatch._snapshot(rows, latest) != expected:
            return False
        if progress.get("requires_cutover") and "feature_baseline" in training:
            return await same_feature_intent(
                db, training["feature_baseline"], await snapshot_feature_values(db, doc.project_id)
            )
        return True
    # Sources published before atomic batches retain per-category checkpoints.
    by_key = {row.category_key: row for row in rows}
    for key in (doc.digest_meta or {}).get("project_training", {}).get("completed", []):
        row = by_key.get(key)
        if row is None or str(row.active_revision_id) != training.get("revision_ids", {}).get(key):
            return False
        active = await db.get(KnowledgeCategoryRevision, row.active_revision_id)
        if active is None or active.revision_no != latest.get(row.id):
            return False
    return True


class TrainingCategoryBatch:
    def __init__(self, db, categories, token: uuid.UUID) -> None:
        self.db = db
        self.categories = categories
        self.token = token

    async def _lock(self, doc):
        doc.metadata_ = await ensure_training_owner(self.db, doc.id, doc.project_id, self.token)
        return await _locked_category_state(self.db, doc.project_id)

    async def check_extraction_baseline(self, doc):
        rows, latest = await self._lock(doc)
        training = doc.metadata_["project_training"]
        # A resumed source owns its staged revisions; compare against that
        # checkpoint instead of treating those writes as an administrator edit.
        expected = (
            training.get("published_snapshot")
            or training.get("batch_snapshot")
            or training.get("extraction_baseline")
        )
        if expected is not None and self._snapshot(rows, latest) != expected:
            raise ConflictError("Project knowledge changed after this training source was uploaded")

    @staticmethod
    def _snapshot(rows, latest):
        return category_snapshot(rows, latest)

    async def _check_snapshot(self, doc):
        rows, latest = await self._lock(doc)
        expected = doc.metadata_["project_training"]["batch_snapshot"]
        if self._snapshot(rows, latest) != expected:
            raise ConflictError("Project knowledge changed while this source was being prepared")
        return rows

    async def stage(self, doc, plan, actor):
        await ensure_training_owner(self.db, doc.id, doc.project_id, self.token)
        await _ensure_category_rows(self.db, doc.project_id)
        rows, latest = await self._lock(doc)
        training = dict(doc.metadata_["project_training"])
        if training.get("batch_snapshot") is None and training.get("extraction_baseline") is not None:
            if self._snapshot(rows, latest) != training["extraction_baseline"]:
                raise ConflictError("Project knowledge changed after this training source was uploaded")
        proposed = {
            write.key.value: parse_category_markdown(write.key, write.content)
            for write in plan.writes
        }
        if training.get("batch_snapshot") is not None:
            # Explicit reprocessing resets the receipt to QUEUED. A source
            # may adopt the pointer graph it published itself, but never an
            # intervening manual edit or a newer source's graph.
            if training.get("published_snapshot") == self._snapshot(rows, latest):
                training["batch_snapshot"] = training["published_snapshot"]
                doc.metadata_ = {**doc.metadata_, "project_training": training}
                await self.db.flush()
            await self._check_snapshot(doc)
            revisions = [
                await self.db.get(
                    KnowledgeCategoryRevision, uuid.UUID(training["revision_ids"][write.key.value])
                )
                for write in plan.writes
            ]
            if any(revision is None for revision in revisions):
                raise ConflictError("A retained training revision no longer exists")
            await self.db.commit()
            return revisions
        # Validate old per-category checkpoints before adopting a legacy retry.
        by_key = {row.category_key: row for row in rows}
        for key in (doc.digest_meta or {}).get("project_training", {}).get("completed", []):
            if str(by_key[key].active_revision_id) != training.get("revision_ids", {}).get(key):
                raise ConflictError("Project knowledge changed after this training checkpoint")
        revisions = []
        for write in plan.writes:
            source_markdown = strip_legacy_job_reference_source(write.content)
            row = by_key[write.key.value]
            active = (
                await self.db.get(KnowledgeCategoryRevision, row.active_revision_id)
                if row.active_revision_id
                else None
            )
            # Reuse only the latest unchanged active content; a pending manual
            # revision remains an intent that this later batch must supersede.
            if (
                active is not None
                and active.revision_no == latest.get(row.id)
                and (
                    active.source_markdown == source_markdown
                    and active.source_filename == write.filename
                )
            ):
                revisions.append(active)
                continue
            revision = KnowledgeCategoryRevision(
                category_id=row.id,
                revision_no=int(latest.get(row.id) or 0) + 1,
                status=KnowledgeCategoryRevisionStatus.STAGED,
                source_filename=write.filename,
                source_markdown=source_markdown,
                normalized_payload=proposed[write.key.value].model_dump(mode="json"),
                content_sha256=category_checksum(proposed[write.key.value]),
                created_by=actor.id,
                quality_result={"project_training_document_id": str(doc.id)},
            )
            self.db.add(revision)
            await self.db.flush()
            latest[row.id] = revision.revision_no
            revisions.append(revision)
            await record_audit(
                self.db,
                action="stage_project_knowledge_category",
                actor_id=actor.id,
                target_type="knowledge_category_revision",
                target_id=str(revision.id),
                payload={"project_id": str(doc.project_id), "category": write.key.value},
            )
        training["revision_ids"] = {
            write.key.value: str(revision.id)
            for write, revision in zip(plan.writes, revisions, strict=True)
        }
        training["batch_snapshot"] = self._snapshot(rows, latest)
        doc.metadata_ = {**doc.metadata_, "project_training": training}
        await self.db.commit()
        return revisions

    async def prepare(self, doc, revision, embedder, llm_json=None):
        revision_id = revision.id
        await self._check_snapshot(doc)
        revision = await self.db.scalar(
            select(KnowledgeCategoryRevision)
            .where(KnowledgeCategoryRevision.id == revision_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if revision.status is KnowledgeCategoryRevisionStatus.ACTIVE:
            await self.db.commit()
            return
        quality = dict(revision.quality_result or {})
        if quality.get("project_training_document_id") != str(doc.id):
            raise ConflictError("Training cannot claim another category update")
        if quality.get("prepared_document_id"):
            prepared = await self.db.get(
                KnowledgeDocument, uuid.UUID(quality["prepared_document_id"])
            )
            count = (
                await self.db.scalar(
                    select(func.count())
                    .select_from(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id == prepared.id)
                )
                if prepared is not None
                else None
            )
            if (
                prepared is None
                or prepared.status != KnowledgeStatus.PROCESSING
                or count != quality["record_count"]
            ):
                raise ConflictError("Prepared category evidence changed before publication")
            await self.db.commit()
            return
        if revision.attempt_count >= MAX_CATEGORY_PROCESSING_ATTEMPTS:
            raise ConflictError("Category processing retry limit reached; submit corrected content")
        revision.attempt_count += 1
        revision.status = KnowledgeCategoryRevisionStatus.PROCESSING
        revision.processing_token = self.token
        revision.lease_expires_at = datetime.fromisoformat(
            doc.metadata_["project_training"]["lease_expires_at"]
        )
        revision.processing_started_at = datetime.now(UTC)
        revision.error_message = revision.failure_code = None
        document = validate_category_payload(
            (await self.db.get(KnowledgeCategory, revision.category_id)).category_key,
            revision.normalized_payload,
        )
        units = render_category_units(document)
        await self.db.commit()  # No source/project lock spans provider I/O.
        try:
            vectors = await embedder.batch([unit["content"] for unit in units])
            if len(vectors) != len(units):
                raise RuntimeError("embedding provider returned an incomplete category batch")
            if self.categories._enforce_retrieval_selftest:
                failures = await retrieval_selftest_failures(document, units, vectors, embedder)
                repair_attempts = 0
                while (
                    failures
                    and llm_json is not None
                    and repair_attempts < SELFTEST_REPAIR_MAX_ATTEMPTS
                ):
                    repair_attempts += 1
                    if not await repair_selftest_records(document, units, failures, llm_json):
                        break  # Nothing was rewritable; keep the real failure.
                    units = render_category_units(document)
                    vectors = await embedder.batch([unit["content"] for unit in units])
                    failures = await retrieval_selftest_failures(
                        document, units, vectors, embedder
                    )
                if failures:
                    raise RetrievalSelftestError(failures)
                if repair_attempts:
                    # The repair changed the record, so the staged markdown and
                    # the payload must say what actually activates — otherwise
                    # the next retry re-parses the rejected label. The commit
                    # here is required: the snapshot re-select below reloads
                    # the row with populate_existing, which would discard the
                    # uncommitted fields.
                    revision.source_markdown = build_source_markdown(
                        document.model_dump(mode="json")
                    )
                    revision.content_sha256 = category_checksum(document)
                    revision.normalized_payload = document.model_dump(mode="json")
                    await self.db.commit()
            await self._check_snapshot(doc)
            revision = await self.db.scalar(
                select(KnowledgeCategoryRevision)
                .where(KnowledgeCategoryRevision.id == revision_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if revision.processing_token != self.token:
                raise ConflictError("Category preparation lost its claimant")
            prepared = KnowledgeDocument(
                file_name=revision.source_filename,
                source="category_markdown",
                status=KnowledgeStatus.PROCESSING,
                raw_text=revision.source_markdown,
                project_id=doc.project_id,
                mime_type="text/markdown",
                stage="PREPARED",
                category_revision_id=revision.id,
                metadata_={
                    "schema_version": "category-1.0",
                    "category": document.category.value,
                    "category_revision_id": str(revision.id),
                    "project_training_document_id": str(doc.id),
                },
            )
            self.db.add(prepared)
            await self.db.flush()
            count = await KnowledgeChunkRepo(self.db).insert_category_revision(
                document_id=prepared.id,
                project_id=doc.project_id,
                category_revision_id=revision.id,
                category_key=document.category.value,
                units_with_vectors=list(zip(units, vectors, strict=True)),
            )
            revision.quality_result = {
                **quality,
                "prepared_document_id": str(prepared.id),
                "record_count": count,
                "embedding_count": len(vectors),
                "checksum": revision.content_sha256,
                "schema_check": "passed",
                "selftest_repair_attempts": repair_attempts,
            }
            revision.processing_token = revision.lease_expires_at = (
                revision.processing_started_at
            ) = None
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            failed = await self.db.scalar(
                select(KnowledgeCategoryRevision)
                .where(KnowledgeCategoryRevision.id == revision_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if failed is not None and failed.processing_token == self.token:
                failed.status = KnowledgeCategoryRevisionStatus.FAILED
                failure_code = (
                    "category_retrieval_selftest_failed"
                    if isinstance(exc, RetrievalSelftestError)
                    else "category_activation_failed"
                )
                failed.failure_code = failure_code
                # The selftest's str() carries the offending queries and their
                # own-record similarities — the detail this gate exists to
                # surface (mirrors KnowledgeCategoryService.activate_revision).
                # Other causes keep the generic operator message.
                failed.error_message = (
                    str(exc)
                    if isinstance(exc, RetrievalSelftestError)
                    else "Category preparation failed"
                )
                failed.processing_token = failed.lease_expires_at = failed.processing_started_at = (
                    None
                )
                await self.db.commit()
            else:
                failure_code = "category_activation_failed"
            # Mirror the row's stable code on the raised error instead of the
            # default: callers and logs must be able to tell a rejected label
            # from an infrastructure failure.
            raise CategoryActivationError(failure_code) from None

    async def publish(self, doc, revisions):
        rows = await self._check_snapshot(doc)
        by_id = {row.id: row for row in rows}
        proposed = {}
        for revision in revisions:
            await self.db.refresh(revision)
            proposed[by_id[revision.category_id].category_key] = validate_category_payload(
                by_id[revision.category_id].category_key, revision.normalized_payload
            )
        project = await locked_project(self.db, doc.project_id)
        changed = []
        for revision in revisions:
            category = by_id[revision.category_id]
            if revision.status is KnowledgeCategoryRevisionStatus.ACTIVE:
                continue
            quality = dict(revision.quality_result or {})
            if (
                quality.get("project_training_document_id") != str(doc.id)
                or quality.get("checksum") != revision.content_sha256
            ):
                raise ConflictError("Training category has no confirmed prepared evidence")
            prepared = await self.db.get(
                KnowledgeDocument, uuid.UUID(quality["prepared_document_id"])
            )
            count = await self.db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == prepared.id)
            )
            if prepared.status != KnowledgeStatus.PROCESSING or count != quality["record_count"]:
                raise ConflictError("Prepared category evidence changed before publication")
            if category.active_revision_id is not None:
                old = await self.db.get(KnowledgeCategoryRevision, category.active_revision_id)
                old.status = KnowledgeCategoryRevisionStatus.ARCHIVED
            category.active_revision_id = revision.id
            category.updated_at = datetime.now(UTC)
            revision.status = KnowledgeCategoryRevisionStatus.ACTIVE
            revision.activated_at = datetime.now(UTC)
            revision.processing_token = revision.lease_expires_at = (
                revision.processing_started_at
            ) = None
            revision.error_message = revision.failure_code = None
            revision.quality_result = {
                **quality,
                "projection": "complete",
                "inserted_chunk_count": count,
            }
            prepared.status = KnowledgeStatus.PUBLISHED
            prepared.stage = "PUBLISHED"
            changed.append(revision)
        await self.db.flush()  # Projections see the complete new pointer graph.
        projection_applied = await category_projection_allowed(self.db, project)
        for revision in changed:
            revision.quality_result = {
                **revision.quality_result,
                "projection": "complete" if projection_applied else "deferred_until_cutover",
            }
        if projection_applied:
            for revision in sorted(
                changed, key=lambda row: by_id[row.category_id].category_key != "jobs"
            ):
                await self.categories._projection_writer.apply_for_revision(
                    doc.project_id, revision, proposed[by_id[revision.category_id].category_key]
                )
            project.category_authority_started = True
        training = dict(doc.metadata_["project_training"])
        training["published_snapshot"] = self._snapshot(
            rows, {row.id: training["batch_snapshot"][row.category_key]["latest"] for row in rows}
        )
        if not projection_applied:
            training["feature_baseline"] = await snapshot_feature_values(self.db, doc.project_id)
        doc.metadata_ = {**doc.metadata_, "project_training": training}
        if projection_applied:
            await publish_training_features(self.db, doc)
        else:
            feature_publication_state(doc, requires_cutover=True, status="DEFERRED_UNTIL_CUTOVER")
        for revision in changed:
            await record_audit(
                self.db,
                action="activate_project_knowledge_category",
                target_type="knowledge_category_revision",
                target_id=str(revision.id),
                payload={
                    "project_id": str(doc.project_id),
                    "category": by_id[revision.category_id].category_key,
                    "record_count": revision.quality_result["record_count"],
                },
            )
        # The caller confirms source COMPLETED and commits this same transaction.

    async def repair_caches(self):
        await self.categories._repair_caches()
