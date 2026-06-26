"""Knowledge ingest + approval (port of VFIC Knowledge Ingest + LLM training pipeline).

Two ingest paths:
  * ``process(embedder, doc, llm_json=None)`` — mechanical 1-chunk fallback (legacy,
    tests, Drive path). When ``llm_json`` is supplied it runs the full LLM
    ``KnowledgePipeline`` (digest -> embed -> index).
  * ``upload_bytes(...)`` — multipart upload: extract text from Office/PDF/text,
    persist the original to a volume, create the doc (stage=UPLOADED); the caller
    then enqueues the async ingest job for the real LLM pipeline.

Approval gates bot usage (only APPROVED docs surface in search).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.vector import vec_literal
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.models.user import User
from app.services.audit_service import record_audit
from app.services.knowledge_pipeline import LLMJson, extract_text

Embedder = Callable[[str], Awaitable[list[float]]]
FileProvider = Callable[[str], Awaitable[bytes]]


class KnowledgeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, doc_id: uuid.UUID) -> KnowledgeDocument | None:
        return await self.db.get(KnowledgeDocument, doc_id)

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
        """Multipart upload: parse the file to text, persist the original, create doc."""
        raw_text = extract_text(file_name, content_type, data)
        storage_path = _persist_original(file_name, data)
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

    async def ingest_from_drive(self, embedder: Embedder, file_provider: FileProvider, drive_file_id: str, file_name: str) -> KnowledgeDocument:
        """Fetch a Drive file's bytes, parse to text, and run process()."""
        raw = await file_provider(drive_file_id)
        content = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        doc = KnowledgeDocument(file_name=file_name, drive_file_id=drive_file_id, raw_text=content, status=KnowledgeStatus.PROCESSING)
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return await self.process(embedder, doc)

    async def process(self, embedder: Embedder, doc: KnowledgeDocument, *, llm_json: LLMJson | None = None) -> KnowledgeDocument:
        """Run the ingest pipeline.

        With ``llm_json`` -> full LLM ``KnowledgePipeline`` (digest/embed/index).
        Without -> mechanical 1-chunk fallback (legacy/tests).
        """
        if llm_json is not None:
            from app.services.knowledge_pipeline import KnowledgePipeline

            await KnowledgePipeline(self.db, embedder, llm_json).run(doc)
            await self.db.refresh(doc)
            return doc

        # --- mechanical fallback: embed 1 chunk-per-doc (whole content) ---
        doc.status = KnowledgeStatus.PROCESSING
        doc.stage = "PROCESSING"
        await self.db.execute(
            text("DELETE FROM knowledge_chunks WHERE document_id = :did"), {"did": str(doc.id)}
        )
        content = doc.raw_text or ""
        emb = vec_literal(await embedder(content))
        await self.db.execute(
            text(
                "INSERT INTO knowledge_chunks(document_id, chunk_index, content, embedding, metadata) "
                "VALUES (:did, 0, :content, CAST(:emb AS vector), CAST('{}' AS jsonb))"
            ),
            {"did": str(doc.id), "content": content, "emb": emb},
        )
        doc.status = KnowledgeStatus.READY_FOR_REVIEW
        doc.stage = "READY_FOR_REVIEW"
        await self.db.commit()
        # rebuild the structured bus graph from the `documents` VIEW (verbatim SQL fn)
        try:
            await self.db.execute(text("SELECT rebuild_bus_timetable_from_documents()"))
            await self.db.commit()
        except Exception:  # noqa: BLE001 — rebuild is best-effort; never block ingest
            pass
        await self.db.refresh(doc)
        return doc

    async def approve(self, doc: KnowledgeDocument, *, actor: User) -> KnowledgeDocument:
        doc.status = KnowledgeStatus.APPROVED
        await record_audit(self.db, action="approve_knowledge", actor_id=actor.id, target_type="knowledge_document", target_id=str(doc.id))
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def reject(self, doc: KnowledgeDocument) -> KnowledgeDocument:
        doc.status = KnowledgeStatus.REJECTED
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def archive(self, doc: KnowledgeDocument, *, actor: User) -> KnowledgeDocument:
        doc.status = KnowledgeStatus.ARCHIVED
        await record_audit(self.db, action="archive_knowledge", actor_id=actor.id, target_type="knowledge_document", target_id=str(doc.id))
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def reindex(self, embedder: Embedder, doc: KnowledgeDocument, *, llm_json: LLMJson | None = None) -> KnowledgeDocument:
        return await self.process(embedder, doc, llm_json=llm_json)

    async def search_test(self, embedder: Embedder, query: str, top_k: int = 10, *, project_id: uuid.UUID | None = None) -> list[dict]:
        emb = vec_literal(await embedder(query))
        # Branch in Python rather than `(:pid IS NULL OR ...)` — asyncpg cannot infer
        # the type of a NULL placeholder used only in an IS-NULL expression.
        if project_id is not None:
            sql = (
                "SELECT c.content, 1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                "FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id "
                "WHERE d.status = 'APPROVED' AND c.embedding IS NOT NULL "
                "AND d.project_id = CAST(:pid AS uuid) "
                "ORDER BY c.embedding <=> CAST(:emb AS vector) LIMIT :k"
            )
            params: dict = {"emb": emb, "k": top_k, "pid": str(project_id)}
        else:
            sql = (
                "SELECT c.content, 1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                "FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id "
                "WHERE d.status = 'APPROVED' AND c.embedding IS NOT NULL "
                "ORDER BY c.embedding <=> CAST(:emb AS vector) LIMIT :k"
            )
            params = {"emb": emb, "k": top_k}
        rows = (await self.db.execute(text(sql), params)).all()
        return [{"content": r.content, "similarity": float(r.similarity)} for r in rows]

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


def _persist_original(file_name: str, data: bytes) -> str | None:
    """Best-effort: write the original upload to the KB volume; return its path."""
    try:
        base = Path(get_settings().kb_storage_path)
        (base).mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in file_name)[:120] or "upload"
        path = base / f"{uuid.uuid4().hex}_{safe}"
        path.write_bytes(data)
        return str(path)
    except Exception:  # noqa: BLE001 — storage is best-effort; raw_text is the source of truth
        return None
