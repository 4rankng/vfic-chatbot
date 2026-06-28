"""Knowledge ingest + publishing (port of VFIC Knowledge Ingest + LLM training pipeline).

Two ingest paths:
  * ``process(embedder, doc, llm_json=None)`` — mechanical 1-chunk fallback (legacy,
    tests). When ``llm_json`` is supplied it runs the full LLM
    ``KnowledgePipeline`` (digest -> embed -> index).
  * ``upload_bytes(...)`` — multipart upload: decode the file as raw text,
    persist the original to a volume, create the doc (stage=UPLOADED); the caller
    then enqueues the async ingest job for the real LLM pipeline.

Successful ingest publishes bot-usable knowledge immediately. Admins remove bad
sources by archiving/replacing them rather than approving a review queue.
"""
from __future__ import annotations

import uuid
from typing import Awaitable, Callable

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector import vec_literal
from app.models.company import Project
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.models.user import User
from app.schemas.knowledge import KnowledgeDocumentUpdate
from app.services.audit_service import record_audit
from app.services.knowledge import LLMJson
from app.services.knowledge.repository import KnowledgeChunkRepo, rebuild_bus_timetable
from app.services.storage import persist_original_upload

Embedder = Callable[[str], Awaitable[list[float]]]


class KnowledgeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, doc_id: uuid.UUID) -> KnowledgeDocument | None:
        return await self.db.get(KnowledgeDocument, doc_id)

    async def list_chunks(self, doc_id: uuid.UUID, *, limit: int = 50) -> list[dict]:
        return await KnowledgeChunkRepo(self.db).list_for_doc(doc_id, limit=limit)

    async def upload(self, file_name: str, content: str, drive_file_id: str | None = None, project_id: uuid.UUID | None = None) -> KnowledgeDocument:
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
        self, file_name: str, content_type: str, data: bytes, *, project_id: uuid.UUID | None = None
    ) -> KnowledgeDocument:
        """Multipart upload: decode the file as raw text, persist the original, create doc."""
        raw_text = data.decode("utf-8", errors="replace")
        storage_path = persist_original_upload(file_name, data)
        doc = KnowledgeDocument(
            file_name=file_name,
            source="upload",
            mime_type=content_type or None,
            storage_path=storage_path,
            raw_text=raw_text,
            project_id=project_id,
            status=KnowledgeStatus.UPLOADED,
            stage="EXTRACTED" if raw_text.strip() else "UPLOADED",
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def process(self, embedder: Embedder, doc: KnowledgeDocument, *, llm_json: LLMJson | None = None) -> KnowledgeDocument:
        """Run the ingest pipeline.

        With ``llm_json`` -> full LLM ``KnowledgePipeline`` (digest/embed/index).
        Without -> mechanical 1-chunk fallback (legacy/tests).
        """
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
        # rebuild the structured bus graph from the `documents` VIEW (best-effort;
        # never block ingest). The repo helper owns the SQL + commit.
        try:
            await rebuild_bus_timetable(self.db)
        except Exception:  # noqa: BLE001
            pass
        await self.db.refresh(doc)
        return doc

    async def archive(self, doc: KnowledgeDocument, *, actor: User) -> KnowledgeDocument:
        doc.status = KnowledgeStatus.ARCHIVED
        await record_audit(self.db, action="archive_knowledge", actor_id=actor.id, target_type="knowledge_document", target_id=str(doc.id))
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def update(self, doc: KnowledgeDocument, body: KnowledgeDocumentUpdate, *, actor: User) -> KnowledgeDocument:
        if body.file_name is not None:
            doc.file_name = body.file_name.strip()
        if "project_id" in body.model_fields_set:
            if body.project_id is not None and await self.db.get(Project, body.project_id) is None:
                from fastapi import HTTPException, status

                raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
            doc.project_id = body.project_id
            await self.db.execute(
                text("UPDATE knowledge_chunks SET project_id = :pid WHERE document_id = :did"),
                {
                    "pid": str(body.project_id) if body.project_id is not None else None,
                    "did": str(doc.id),
                },
            )
        await record_audit(self.db, action="update_knowledge", actor_id=actor.id, target_type="knowledge_document", target_id=str(doc.id))
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def delete(self, doc: KnowledgeDocument, *, actor: User) -> None:
        target_id = str(doc.id)
        await record_audit(self.db, action="delete_knowledge", actor_id=actor.id, target_type="knowledge_document", target_id=target_id)
        await self.db.delete(doc)
        await self.db.commit()

    async def reindex(self, embedder: Embedder, doc: KnowledgeDocument, *, llm_json: LLMJson | None = None) -> KnowledgeDocument:
        return await self.process(embedder, doc, llm_json=llm_json)

    async def search_test(self, embedder: Embedder, query: str, top_k: int = 10, *, project_id: uuid.UUID | None = None) -> list[dict]:
        emb = vec_literal(await embedder(query))
        return await KnowledgeChunkRepo(self.db).search_similar(emb, top_k, project_id=project_id)

    async def list(self, *, status_: KnowledgeStatus | None = None, project_id: uuid.UUID | None = None) -> list[KnowledgeDocument]:
        q = select(KnowledgeDocument)
        if status_ is not None:
            q = q.where(KnowledgeDocument.status == status_)
        if project_id is not None:
            q = q.where(KnowledgeDocument.project_id == project_id)
        return list((await self.db.scalars(q.order_by(desc(KnowledgeDocument.created_at)))).all())

    async def reconcile(self, current_drive_ids: list[str]) -> int:
        """Drop knowledge_documents whose drive_file_id is no longer in Drive (cascades chunks)."""
        res = await self.db.execute(
            text(
                "DELETE FROM knowledge_documents WHERE drive_file_id IS NOT NULL "
                "AND drive_file_id <> ALL(CAST(:ids AS text[]))"
            ),
            {"ids": current_drive_ids},
        )
        await self.db.commit()
        return res.rowcount or 0
