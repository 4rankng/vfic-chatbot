"""Knowledge ingest + publishing service.

Two ingest paths:
  * ``process(embedder, doc, llm_json=None)`` — mechanical 1-chunk fallback (legacy,
    tests). When ``llm_json`` is supplied it runs the full LLM
    ``KnowledgePipeline`` (digest -> embed -> index).
  * ``upload_bytes(...)`` — multipart upload: extract text from the source file,
    persist the original to a volume, create the doc (stage=UPLOADED); the caller
    then enqueues the async ingest job for the real LLM pipeline.

Successful ingest publishes bot-usable knowledge immediately. Admins remove bad
sources by archiving/replacing them rather than approving a review queue.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_kb_caches
from app.core.vector import vec_literal
from app.models.company import Project
from app.models.knowledge import (
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.models.user import User
from app.schemas.knowledge import KnowledgeDocumentUpdate
from app.services.audit_service import record_audit
from app.services.ingestion.limits import assert_upload_size
from app.shared.domain.errors import ConflictError, NotFoundError, UpstreamError
from app.services.knowledge import LLMJson
from app.services.knowledge.canonical import checksum_text
from app.services.knowledge.file_extraction import (
    DOCX_MIME_TYPE,
    KnowledgeFileExtractionError,
    _detect_upload_format,
    extraction_method_for_format,
    extract_text,
)
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo
from app.services.knowledge.document_repository import KnowledgeDocumentRepo
from app.services.knowledge.project_index_repository import rebuild_bus_timetable
from app.services.storage import persist_original_upload
from app.project_knowledge.application.jobs import ProjectKnowledgeJobs

Embedder = Callable[[str], Awaitable[list[float]]]


class KnowledgeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._jobs: ProjectKnowledgeJobs | None = None

    def _job_scheduler(self) -> ProjectKnowledgeJobs:
        if self._jobs is None:
            from app.composition.project_knowledge_jobs import build_project_knowledge_jobs

            self._jobs = build_project_knowledge_jobs()
        return self._jobs

    async def get(self, doc_id: uuid.UUID) -> KnowledgeDocument | None:
        return await self.db.get(KnowledgeDocument, doc_id)

    async def assert_source_reprocessable(self, doc: KnowledgeDocument) -> None:
        if (doc.metadata_ or {}).get("project_training"):
            from app.services.knowledge.category_authority import require_category_project

            if doc.project_id is None:
                raise ConflictError("Nguồn đào tạo chưa thuộc dự án. Vui lòng chọn dự án rồi nạp lại tệp.")
            await require_category_project(self.db, doc.project_id)
        else:
            await self.assert_mutable(doc.project_id, allow_authoritative=True)

    async def queue_document(self, doc, *, jobs, reuse_completed=False) -> None:
        """Persist truthful retry state and require broker acceptance of its source."""
        from app.services.knowledge.project_training import training_progress

        async def locked_source():
            if doc.project_id is not None:
                await self.db.scalar(select(Project.id).where(Project.id == doc.project_id).with_for_update())
            return await self.db.scalar(
                select(KnowledgeDocument).where(KnowledgeDocument.id == doc.id).with_for_update()
                .execution_options(populate_existing=True)
            )

        locked = await locked_source()
        if locked is None:
            raise NotFoundError("document not found")
        training = (locked.metadata_ or {}).get("project_training")
        if training is not None:
            lease = training.get("lease_expires_at")
            if lease and datetime.fromisoformat(lease) > datetime.now(UTC):
                await self.db.commit()
                return
            if reuse_completed and (locked.digest_meta or {}).get("project_training", {}).get("status") == "COMPLETED":
                await self.db.commit()
                return
            training_progress(locked, status="QUEUED", current=None, error=None)
            locked.metadata_ = {**(locked.metadata_ or {}), "project_training": {
                **training, "processing_token": None, "lease_expires_at": None,
            }}
        locked.status = KnowledgeStatus.UPLOADED
        locked.stage = "EXTRACTED"
        locked.error = None
        await self.db.commit()
        try:
            jobs.ingest_document(locked.id)
        except Exception as exc:
            latest = await locked_source()
            progress = (latest.digest_meta or {}).get("project_training", {}) if latest is not None else {}
            if progress.get("status") == "COMPLETED":
                await self.db.commit()
                return  # A broker receipt was lost after the worker completed.
            latest_training = (latest.metadata_ or {}).get("project_training", {}) if latest is not None else {}
            lease = latest_training.get("lease_expires_at")
            alive = bool(lease and datetime.fromisoformat(lease) > datetime.now(UTC))
            if latest is not None and not alive:
                latest.status = KnowledgeStatus.FAILED
                latest.stage = "FAILED"
                latest.error = "Hàng đợi xử lý chưa sẵn sàng. Vui lòng thử xử lý lại tệp đã lưu."
                if training is not None:
                    training_progress(latest, status="FAILED", error=latest.error)
                await self.db.commit()
            else:
                await self.db.commit()
            raise UpstreamError("Hàng đợi xử lý chưa sẵn sàng. Vui lòng thử xử lý lại tệp đã lưu.") from exc

    

    

    

    

    

    

    

    async def reindex_all(self, actor: User) -> int:
        docs = (
            await self.db.scalars(
                select(KnowledgeDocument)
                .join(Project, Project.id == KnowledgeDocument.project_id)
                .where(
                    KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
                    KnowledgeDocument.project_id.is_not(None),
                    Project.knowledge_base_id.is_(None),
                    KnowledgeDocument.raw_text.is_not(None),
                )
            )
        ).all()
        for doc in docs:
            self._job_scheduler().ingest_document(doc.id)
        queued = len(docs)
        await bump_kb_caches()
        await record_audit(
            self.db,
            action="knowledge_relearn_all_enqueued",
            actor_id=actor.id,
            target_type="knowledge",
            target_id="all",
            payload={"queued": queued},
        )
        await self.db.commit()
        return queued

    async def list_chunks(self, doc_id: uuid.UUID, *, limit: int = 50) -> list[dict]:
        return await KnowledgeChunkRepo(self.db).list_for_doc(doc_id, limit=limit)

    async def upload(
        self,
        file_name: str,
        content: str,
        drive_file_id: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> KnowledgeDocument:
        await self.assert_mutable(project_id, allow_authoritative=True)
        doc = KnowledgeDocument(
            file_name=file_name,
            drive_file_id=drive_file_id,
            raw_text=content,
            project_id=project_id,
            status=KnowledgeStatus.UPLOADED,
            stage="UPLOADED",
            source="google_drive" if drive_file_id else "upload",
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def upload_bytes(
        self,
        file_name: str,
        content_type: str,
        data: bytes,
        *,
        project_id: uuid.UUID | None = None,
        training_plan=None,
        auto_extract: bool = False,
        actor=None,
    ) -> KnowledgeDocument:
        """Multipart upload: extract text, persist the original, create doc."""
        # SEC-05: the caller already checks Content-Length / the route guard, but
        # the service is the single entry point both upload paths funnel through.
        assert_upload_size(len(data))
        training_created_at = None
        is_training = training_plan is not None or auto_extract
        if is_training and (project_id is None or actor is None):
            raise KnowledgeFileExtractionError("Chọn dự án và dùng tài khoản quản trị để nạp kiến thức.")
        if training_plan is not None:
            from app.services.knowledge.project_training import validate_training_plan

            if project_id is None or actor is None:
                raise KnowledgeFileExtractionError("Chọn dự án và dùng tài khoản quản trị để nạp kiến thức.")
            try:
                validate_training_plan(training_plan)
            except ValueError as exc:
                raise KnowledgeFileExtractionError("Nội dung danh mục chưa hợp lệ. Vui lòng kiểm tra tệp rồi thử lại.") from exc
        extracted_text, source_metadata = await asyncio.to_thread(
            self._extract_upload_text, file_name, content_type, data
        )
        # Uploaded text is always SOURCE — the flexible training/freeform lane
        # (brief → deterministic plan, category bundle → sections, anything
        # else → LLM category mapping). The legacy vfic-knowledge-v1 canonical
        # contract no longer intercepts or rejects uploads.
        raw_text = extracted_text
        if not is_training:
            await self.assert_mutable(project_id, allow_authoritative=True)
        else:
            from app.services.knowledge.category_authority import require_category_project

            if project_id is None or actor is None:
                raise KnowledgeFileExtractionError("Chọn dự án và dùng tài khoản quản trị để nạp kiến thức.")
            await require_category_project(self.db, project_id)
        if is_training:
            # Serialize source retention against a worker's final category
            # cutover check, so an older source cannot publish over this one.
            await self.db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        metadata: dict[str, Any] = {}
        version: str | None = None
        metadata["source_file"] = source_metadata
        if is_training:
            if actor is None:
                raise KnowledgeFileExtractionError("Dùng tài khoản quản trị để nạp kiến thức.")
            if not raw_text.strip():
                raise KnowledgeFileExtractionError("Tệp kiến thức không có nội dung. Vui lòng chọn tệp khác.")
            if training_plan is not None:
                metadata["project_training"] = {
                    **training_plan.model_dump(mode="json"),
                    "actor_id": str(actor.id),
                    "plan_sha256": checksum_text(training_plan.model_dump_json()),
                }
            else:
                from app.services.knowledge.extraction import CATEGORY_PLAN_VERSION
                from app.services.knowledge.category_batch import capture_training_baseline
                from app.services.knowledge.training_features import capture_auto_training_feature_baseline

                metadata["project_training"] = {
                    "writes": [],
                    "auto_extract": True,
                    "actor_id": str(actor.id),
                    "plan_sha256": checksum_text(
                        f"{CATEGORY_PLAN_VERSION}:{source_metadata['text_checksum']}"
                    ),
                    "extraction_baseline": await capture_training_baseline(self.db, project_id),
                    "auto_feature_baseline": await capture_auto_training_feature_baseline(self.db, project_id),
                }
            existing = await self.db.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.project_id == project_id,
                    KnowledgeDocument.source == "upload",
                    KnowledgeDocument.metadata_["project_training"]["plan_sha256"].as_string()
                    .is_not(None),
                    KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
                ).order_by(KnowledgeDocument.created_at.desc()).limit(1)
            )
            if existing is not None and (
                (existing.metadata_ or {}).get("source_file", {}).get("text_checksum")
                == source_metadata["text_checksum"]
                and (existing.metadata_ or {}).get("project_training", {}).get("plan_sha256")
                == metadata["project_training"]["plan_sha256"]
            ):
                from app.services.knowledge.category_batch import training_source_reusable

                if await training_source_reusable(self.db, existing):
                    return existing
            # now() is a transaction-start timestamp in PostgreSQL. Stamp
            # after the project lock instead, preserving actual source order
            # even when requests began their transactions in reverse order.
            training_created_at = max(
                datetime.now(UTC),
                existing.created_at + timedelta(microseconds=1) if existing is not None else datetime.min.replace(tzinfo=UTC),
            )
        storage_path = await asyncio.to_thread(persist_original_upload, file_name, data)
        doc = KnowledgeDocument(
            file_name=file_name,
            source="upload",
            version=version,
            mime_type=content_type or None,
            storage_path=storage_path,
            raw_text=raw_text,
            metadata_=metadata,
            project_id=project_id,
            status=KnowledgeStatus.UPLOADED,
            stage="EXTRACTED" if raw_text.strip() else "UPLOADED",
            digest_meta={"project_training": {
                "status": "QUEUED", "current": None, "completed": [], "error": None,
            }} if is_training else {},
        )
        self.db.add(doc)
        if training_created_at is not None:
            doc.created_at = training_created_at
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    @staticmethod
    def _extract_upload_text(file_name: str, content_type: str, data: bytes) -> tuple[str, dict]:
        """Return ingestable text plus source-file metadata for an upload.

        The decode itself belongs to ``file_extraction``; this only assembles
        the ``source_file`` metadata the document carries. ``extraction`` names
        the mechanism ``extract_text`` actually used for the resolved format —
        it is read from the same table that drives the dispatch, so the
        recorded provenance cannot drift from what the code did.
        """
        file_format = _detect_upload_format(file_name, content_type)
        text = extract_text(file_name, content_type, data, decode_errors="strict")
        if file_format == "docx" and not text.strip():
            raise KnowledgeFileExtractionError("DOCX không có văn bản để ingest.")
        if file_format == "xlsx" and not text.strip():
            raise KnowledgeFileExtractionError("XLSX không có dữ liệu để ingest.")
        return text, {
            "format": file_format,
            "mime_type": content_type or (DOCX_MIME_TYPE if file_format == "docx" else None),
            "extraction": extraction_method_for_format(
                file_format, data=data, content_type=content_type
            ),
            "text_checksum": checksum_text(text),
        }

    async def process(
        self, embedder: Embedder, doc: KnowledgeDocument, *, llm_json: LLMJson | None = None
    ) -> KnowledgeDocument:
        """Run the ingest pipeline.

        With ``llm_json`` -> full LLM ``KnowledgePipeline`` (digest/embed/index).
        Without -> mechanical 1-chunk fallback (legacy/tests).
        """
        await self.assert_mutable(doc.project_id)
        if llm_json is not None:
            from app.services.knowledge import KnowledgePipeline

            await KnowledgePipeline(self.db, embedder, llm_json).run(doc)
            await self.db.refresh(doc)
            return doc

        # --- mechanical fallback: embed 1 chunk-per-doc (whole content) ---
        doc.status = KnowledgeStatus.PROCESSING
        doc.stage = "PROCESSING"
        content = doc.raw_text or ""
        emb = vec_literal(await embedder(content))
        await KnowledgeChunkRepo(self.db).replace_with_single_chunk(doc, content, emb)
        doc.status = KnowledgeStatus.PUBLISHED
        doc.stage = "PUBLISHED"
        await self.db.commit()
        await bump_kb_caches()
        # rebuild the structured bus graph from the `documents` VIEW (best-effort;
        # never block ingest). The repo helper owns the SQL + commit.
        try:
            await rebuild_bus_timetable(self.db)
        except Exception:  # noqa: BLE001
            pass
        await self.db.refresh(doc)
        return doc

    async def archive(self, doc: KnowledgeDocument, *, actor: User) -> KnowledgeDocument:
        await self.assert_mutable(doc.project_id)
        doc.status = KnowledgeStatus.ARCHIVED
        await record_audit(
            self.db,
            action="archive_knowledge",
            actor_id=actor.id,
            target_type="knowledge_document",
            target_id=str(doc.id),
        )
        await self.db.commit()
        await bump_kb_caches()
        await self.db.refresh(doc)
        return doc

    async def update(
        self, doc: KnowledgeDocument, body: KnowledgeDocumentUpdate, *, actor: User
    ) -> KnowledgeDocument:
        await self.assert_mutable(doc.project_id)
        if body.file_name is not None:
            doc.file_name = body.file_name.strip()
        if "project_id" in body.model_fields_set:
            if body.project_id is not None and await self.db.get(Project, body.project_id) is None:
                raise NotFoundError("project not found")
            await self.assert_mutable(body.project_id)
            doc.project_id = body.project_id
            await KnowledgeChunkRepo(self.db).reassign_project(doc.id, body.project_id)
        await record_audit(
            self.db,
            action="update_knowledge",
            actor_id=actor.id,
            target_type="knowledge_document",
            target_id=str(doc.id),
        )
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def delete(self, doc: KnowledgeDocument, *, actor: User) -> None:
        await self.assert_mutable(doc.project_id)
        target_id = str(doc.id)
        await record_audit(
            self.db,
            action="delete_knowledge",
            actor_id=actor.id,
            target_type="knowledge_document",
            target_id=target_id,
        )
        await self.db.delete(doc)
        await self.db.commit()

    async def reindex(
        self, embedder: Embedder, doc: KnowledgeDocument, *, llm_json: LLMJson | None = None
    ) -> KnowledgeDocument:
        return await self.process(embedder, doc, llm_json=llm_json)

    async def search_test(
        self,
        embedder: Embedder,
        query: str,
        top_k: int = 10,
        *,
        project_id: uuid.UUID | None = None,
    ) -> list[dict]:
        emb = vec_literal(await embedder(query))
        return await KnowledgeChunkRepo(self.db).search_similar(emb, top_k, project_id=project_id)

    async def list(
        self,
        *,
        status_: KnowledgeStatus | None = None,
        project_id: uuid.UUID | None = None,
        stage: str | None = None,
        needs_review: bool | None = None,
        q: str | None = None,
        sort_by: str | None = None,
        order: str | None = "desc",
        page: int = 1,
        per_page: int = 25,
    ) -> tuple[list[KnowledgeDocument], int]:
        query = select(KnowledgeDocument).outerjoin(
            Project,
            KnowledgeDocument.project_id == Project.id,
        )
        if status_ is not None:
            query = query.where(KnowledgeDocument.status == status_)
        if project_id is not None:
            query = query.where(KnowledgeDocument.project_id == project_id)
        if stage:
            query = query.where(func.upper(KnowledgeDocument.stage) == stage.upper())
        if needs_review is True:
            flagged_count = func.coalesce(
                func.jsonb_array_length(KnowledgeDocument.digest_meta["flagged_unit_indexes"]),
                0,
            )
            query = query.where(
                (flagged_count > 0)
                | (KnowledgeDocument.status == KnowledgeStatus.FAILED)
                | (func.upper(KnowledgeDocument.stage).in_(["FAILED", "ERROR"]))
            )
        if q:
            pat = f"%{q.strip()}%"
            ua = func.extensions.unaccent
            query = query.where(
                ua(KnowledgeDocument.file_name).ilike(ua(pat))
                | ua(KnowledgeDocument.source).ilike(ua(pat))
                | ua(KnowledgeDocument.mime_type).ilike(ua(pat))
                | ua(KnowledgeDocument.digest_summary).ilike(ua(pat))
                | ua(KnowledgeDocument.stage).ilike(ua(pat))
                | ua(Project.name).ilike(ua(pat))
            )

        sort_map = {
            "created_at": KnowledgeDocument.created_at,
            "updated_at": KnowledgeDocument.updated_at,
            "file_name": KnowledgeDocument.file_name,
            "stage": KnowledgeDocument.stage,
            "status": KnowledgeDocument.status,
        }
        sort_col = sort_map.get((sort_by or "").lower()) or KnowledgeDocument.created_at
        order_expr = sort_col.asc() if (order or "desc").lower() == "asc" else sort_col.desc()
        total = await self.db.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await self.db.scalars(
                query.order_by(order_expr).offset((page - 1) * per_page).limit(per_page)
            )
        ).all()
        project_ids = {row.project_id for row in rows if row.project_id is not None}
        if project_ids:
            project_rows = (
                await self.db.execute(
                    select(Project.id, Project.name).where(Project.id.in_(project_ids))
                )
            ).all()
            project_names = {row.id: row.name for row in project_rows}
            for row in rows:
                # A transient view attribute, not a column: setattr because the
                # ORM model does not declare it and instance __dict__ is typed
                # read-only.
                setattr(row, "project_name", project_names.get(row.project_id))
        return list(rows), int(total or 0)

    async def reconcile(self, current_drive_ids: list[str]) -> int:
        """Drop knowledge_documents whose drive_file_id is no longer in Drive (cascades chunks)."""
        return await KnowledgeDocumentRepo(self.db).delete_orphans_by_drive_ids(current_drive_ids)

    

    async def assert_mutable(
        self, project_id: uuid.UUID | None, *, allow_authoritative: bool = False
    ) -> None:
        """Precondition for every legacy knowledge mutation on ``project_id``.

        Keep Project-owned knowledge exclusive to its selected mode: unowned
        legacy Projects remain readable/mutable during migration, while an owned
        Project can only change knowledge through Single-page PUT or a category
        YAML replacement. Callers include the router (fail-fast before enqueueing
        a background ingest) and every legacy mutation method below.

        ``allow_authoritative`` opens the source-document lane — upload and
        (re)ingest — for an owned Project whose knowledge is category-authoritative
        (``category_authority_started``). Its card/features/jobs belong to the
        category projections and the pipeline's card protection keeps document
        ingest content-only there, so storing or retraining a source document
        (a project brief, say) cannot clobber the authority.
        """
        if project_id is None:
            return
        project = await self.db.get(Project, project_id)
        if project is None:
            raise NotFoundError("project not found")
        if getattr(project, "knowledge_base_id", None) is not None and not (
            allow_authoritative and project.category_authority_started
        ):
            raise ConflictError(
                "Project knowledge is managed only through its Single-page or category YAML API"
            )
