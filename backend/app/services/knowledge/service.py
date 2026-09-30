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

import hashlib
import uuid
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_kb_caches
from app.core.vector import vec_literal
from app.models.company import Project
from app.models.knowledge import (
    KBTextFile,
    KBVersion,
    KBVersionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.models.user import User
from app.schemas.knowledge import KnowledgeDocumentUpdate
from app.services.audit_service import record_audit
from app.services.ingestion.limits import assert_upload_size
from app.shared.domain.errors import ConflictError, NotFoundError
from app.services.knowledge import LLMJson
from app.services.knowledge.canonical import (
    CANONICAL_SCHEMA_VERSIONS,
    SCHEMA_VERSION,
    checksum_text,
    parse_canonical_markdown,
)
from app.services.knowledge.bus_timetable.repair import repair_canonical_markdown
from app.services.knowledge.file_extraction import (
    DOCX_MIME_TYPE,
    KB_RELEASE_FORMATS,
    KnowledgeFileExtractionError,
    _detect_upload_format,
    extraction_method_for_format,
    extract_text,
    mime_type_for_format,
)
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo
from app.services.knowledge.document_repository import KnowledgeDocumentRepo
from app.services.knowledge.project_index_repository import rebuild_bus_timetable
from app.services.knowledge.text_ingestion import kb_text_stats
from app.services.storage import persist_original_upload
from app.project_knowledge.application.jobs import ProjectKnowledgeJobs

Embedder = Callable[[str], Awaitable[list[float]]]


def _declares_canonical(text: str) -> bool:
    """True when the document declares the canonical Markdown schema up front."""
    return "schema_version:" in text[:1000]


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

    async def get_version(self, version_id: uuid.UUID) -> KBVersion | None:
        return await self.db.get(KBVersion, version_id)

    async def create_version(self, project_id: uuid.UUID, *, actor: User) -> KBVersion:
        project = await self.db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if project is None:
            raise NotFoundError("project not found")
        if getattr(project, "knowledge_base_id", None) is not None:
            raise ConflictError(
                "Project knowledge is managed only through its Single-page or category YAML API"
            )
        next_version = int(
            await self.db.scalar(
                select(func.coalesce(func.max(KBVersion.version_no), 0) + 1).where(
                    KBVersion.project_id == project_id
                )
            )
            or 1
        )
        version = KBVersion(
            project_id=project_id,
            version_no=next_version,
            status=KBVersionStatus.DRAFT,
            created_by=actor.id,
            template_version_id=None,
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def list_versions(self, project_id: uuid.UUID) -> list[KBVersion]:
        if await self.db.get(Project, project_id) is None:
            raise NotFoundError("project not found")
        return list(
            (
                await self.db.scalars(
                    select(KBVersion)
                    .where(KBVersion.project_id == project_id)
                    .order_by(KBVersion.version_no.desc())
                )
            ).all()
        )

    async def list_version_files(self, version_id: uuid.UUID) -> list[KBTextFile]:
        return list(
            (
                await self.db.scalars(
                    select(KBTextFile)
                    .where(KBTextFile.kb_version_id == version_id)
                    .order_by(KBTextFile.created_at.asc())
                )
            ).all()
        )

    async def upload_text_file(
        self,
        *,
        project_id: uuid.UUID,
        version_id: uuid.UUID,
        file_name: str,
        content_type: str,
        data: bytes,
        actor: User,
    ) -> KBTextFile:
        version = await self.require_version(project_id, version_id)
        if version.status not in {KBVersionStatus.DRAFT, KBVersionStatus.FAILED}:
            raise ValueError("Only DRAFT or FAILED KB versions accept uploads.")
        upload_format = _detect_upload_format(
            file_name, content_type, allowed_formats=KB_RELEASE_FORMATS
        )
        raw = extract_text(
            file_name,
            content_type,
            data,
            allowed_formats=KB_RELEASE_FORMATS,
            decode_errors="replace",
        )
        if upload_format == "docx" and not raw.strip():
            raise KnowledgeFileExtractionError("DOCX không có văn bản để ingest.")
        stats = kb_text_stats(raw)
        if not stats.normalized_text:
            raise ValueError("Uploaded knowledge file is empty.")
        metadata: dict[str, Any] = {}
        source_version: str | None = str(version.version_no)
        if _declares_canonical(stats.normalized_text):
            repair = repair_canonical_markdown(stats.normalized_text)
            canonical = parse_canonical_markdown(repair.text)
            stats = kb_text_stats(repair.text)
            metadata, source_version = self._build_canonical_metadata(
                canonical, stats.normalized_text, raw, repair
            )
        metadata["kb_version_id"] = str(version.id)
        metadata["content_sha256"] = stats.content_sha256
        metadata["source_file"] = {
            "format": upload_format,
            "filename": file_name,
            "extraction": extraction_method_for_format(upload_format),
        }
        doc = KnowledgeDocument(
            file_name=file_name,
            source="kb_version",
            version=source_version,
            mime_type=mime_type_for_format(upload_format, content_type),
            raw_text=stats.normalized_text,
            project_id=project_id,
            status=KnowledgeStatus.UPLOADED,
            stage="EXTRACTED",
            metadata_=metadata,
        )
        self.db.add(doc)
        await self.db.flush()
        text_file = KBTextFile(
            project_id=project_id,
            kb_version_id=version.id,
            document_id=doc.id,
            filename=file_name,
            mime_type=doc.mime_type or "text/plain",
            raw_text=raw,
            normalized_text=stats.normalized_text,
            content_sha256=stats.content_sha256,
            char_count=stats.char_count,
            line_count=stats.line_count,
            uploaded_by=actor.id,
        )
        self.db.add(text_file)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("This file content already exists in the KB version.") from exc
        await self.db.refresh(text_file)
        return text_file

    async def ingest_version(
        self,
        embedder: Embedder,
        version: KBVersion,
        *,
        llm_json: LLMJson,
    ) -> KBVersion:
        await self.assert_mutable(version.project_id)
        files = await self.list_version_files(version.id)
        if not files:
            raise ValueError("KB version has no uploaded text files.")
        version.status = KBVersionStatus.INDEXING
        version.error_message = None
        await self.db.commit()
        chunks = KnowledgeChunkRepo(self.db)
        await chunks.clear_version(version.id)
        try:
            from app.services.knowledge import KnowledgePipeline

            for text_file in files:
                if text_file.document_id is None:
                    raise ValueError(f"KB file {text_file.filename} is missing source document.")
                doc = await self.db.get(KnowledgeDocument, text_file.document_id)
                if doc is None:
                    raise ValueError(f"Source document for {text_file.filename} was deleted.")
                doc.raw_text = text_file.normalized_text
                doc.project_id = version.project_id
                doc.status = KnowledgeStatus.UPLOADED
                doc.stage = "EXTRACTED"
                doc.error = None
                await self.db.commit()
                await KnowledgePipeline(self.db, embedder, llm_json).run(doc)
                await chunks.attach_doc_chunks_to_file(
                    doc_id=doc.id,
                    kb_version_id=version.id,
                    file_id=text_file.id,
                    project_id=version.project_id,
                    source_text=text_file.normalized_text,
                )
                await self.db.commit()
            version.release_manifest_sha256 = hashlib.sha256(
                "|".join(sorted(item.content_sha256 for item in files)).encode()
            ).hexdigest()
            version.error_message = None
            version.status = KBVersionStatus.READY
            await self.db.commit()
        except Exception as exc:
            version.status = KBVersionStatus.FAILED
            version.error_message = f"{type(exc).__name__}: {exc}"[:1000]
            await self.db.commit()
            raise
        await self.db.refresh(version)
        return version

    async def publish_version(self, project_id: uuid.UUID, version_id: uuid.UUID) -> KBVersion:
        await self.assert_mutable(project_id)
        # Serialize concurrent publishes per project so the archive-others-then-
        # activate pair cannot race the unique partial index on ACTIVE versions.
        locked_project = await self.db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        if locked_project is None:
            raise NotFoundError("project not found")
        version = await self.require_version(project_id, version_id)
        if version.status not in {KBVersionStatus.READY, KBVersionStatus.ACTIVE}:
            raise ValueError("Only READY KB versions can be published.")
        await self.db.execute(
            text(
                "UPDATE kb_versions "
                "SET status = 'ARCHIVED' "
                "WHERE project_id = :pid AND status = 'ACTIVE' AND id <> :vid"
            ),
            {"pid": str(project_id), "vid": str(version_id)},
        )
        await self.db.execute(
            text(
                "UPDATE kb_versions "
                "SET status = 'ACTIVE', published_at = now(), error_message = NULL "
                "WHERE id = :vid"
            ),
            {"vid": str(version_id)},
        )
        await self.db.execute(
            text(
                "UPDATE projects SET active_kb_version_id = :vid, updated_at = now() WHERE id = :pid"
            ),
            {"pid": str(project_id), "vid": str(version_id)},
        )
        await self.db.commit()
        await bump_kb_caches()
        await self.db.refresh(version)
        return version

    async def reindex_all(self, actor: User) -> int:
        active_versioned_document_ids = (
            select(KBTextFile.document_id)
            .join(KBVersion, KBVersion.id == KBTextFile.kb_version_id)
            .where(KBVersion.status == KBVersionStatus.ACTIVE)
        )
        has_version_file = select(KBTextFile.id).where(KBTextFile.document_id == KnowledgeDocument.id)
        docs = (
            await self.db.scalars(
                select(KnowledgeDocument)
                .join(Project, Project.id == KnowledgeDocument.project_id)
                .where(
                    KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
                    KnowledgeDocument.project_id.is_not(None),
                    Project.knowledge_base_id.is_(None),
                    KnowledgeDocument.raw_text.is_not(None),
                    (
                        KnowledgeDocument.id.in_(active_versioned_document_ids)
                        | ~has_version_file.exists()
                    ),
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
    ) -> KnowledgeDocument:
        """Multipart upload: extract text, persist the original, create doc."""
        # SEC-05: the caller already checks Content-Length / the route guard, but
        # the service is the single entry point both upload paths funnel through.
        assert_upload_size(len(data))
        extracted_text, source_metadata = self._extract_upload_text(file_name, content_type, data)
        # Canonical-if-declared, the same contract as ``upload_text_file``: a
        # freeform document (a project brief, say) ingests as-is, while text that
        # declares the canonical schema is repaired, validated and carries
        # canonical metadata. A malformed declared-canonical upload is rejected
        # (``CanonicalValidationError``) instead of silently downgraded.
        is_canonical = source_metadata["format"] != "docx" and _declares_canonical(extracted_text)
        repair = repair_canonical_markdown(extracted_text) if is_canonical else None
        raw_text = repair.text if repair is not None else extracted_text
        canonical = parse_canonical_markdown(raw_text) if is_canonical else None
        if canonical is not None and project_id is None:
            project_id = await self._resolve_project_from_canonical(canonical)
        await self.assert_mutable(project_id, allow_authoritative=True)
        metadata, version = self._build_canonical_metadata(
            canonical, raw_text, extracted_text, repair
        )
        metadata["source_file"] = source_metadata
        storage_path = persist_original_upload(file_name, data)
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
        )
        self.db.add(doc)
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
        text = extract_text(file_name, content_type, data, decode_errors="replace")
        if file_format == "docx" and not text.strip():
            raise KnowledgeFileExtractionError("DOCX không có văn bản để ingest.")
        return text, {
            "format": file_format,
            "mime_type": content_type or (DOCX_MIME_TYPE if file_format == "docx" else None),
            "extraction": extraction_method_for_format(file_format),
            "text_checksum": checksum_text(text),
        }

    async def _resolve_project_from_canonical(self, canonical: Any) -> uuid.UUID | None:
        """Look up a project by slug from the canonical document metadata."""
        slug = str(canonical.metadata.get("project_slug") or "").strip()
        if not slug:
            return None
        project = (
            await self.db.scalars(
                select(Project).where(func.lower(Project.slug) == slug.lower()).limit(1)
            )
        ).first()
        return project.id if project else None

    @staticmethod
    def _build_canonical_metadata(
        canonical: Any, raw_text: str, original_text: str, repair: Any
    ) -> tuple[dict, str | None]:
        """Assemble the metadata dict and version for a canonical document."""
        if canonical is None:
            return {}, None
        version = str(canonical.metadata.get("doc_version") or "")
        schema_version = str(canonical.metadata.get("schema_version") or SCHEMA_VERSION)
        if schema_version not in CANONICAL_SCHEMA_VERSIONS:
            schema_version = SCHEMA_VERSION
        canonical_meta: dict = {
            "document": canonical.metadata,
            "validation": {
                "chunk_count": len(canonical.chunks),
                "bus_route_count": len(canonical.bus_timetable.routes),
                "bus_stop_count": sum(len(route.stops) for route in canonical.bus_timetable.routes),
            },
        }
        if repair is not None and repair.changed:
            canonical_meta["repair"] = {
                "applied": True,
                "count": len(repair.repairs),
                "fixes": repair.repairs,
                "original_checksum": checksum_text(original_text),
            }
        metadata = {
            "schema_version": schema_version,
            "checksum": checksum_text(raw_text),
            "canonical": canonical_meta,
        }
        return metadata, version

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

    async def require_version(self, project_id: uuid.UUID, version_id: uuid.UUID) -> KBVersion:
        """Load a KB version owned by ``project_id`` or raise NotFoundError."""
        version = await self.db.get(KBVersion, version_id)
        if version is None or version.project_id != project_id:
            raise NotFoundError("KB version not found")
        return version

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
