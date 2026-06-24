"""Knowledge ingest + approval (port of VFIC Knowledge Ingest).

ingest flow: download/parse -> delete existing chunks for the file -> embed 1
chunk-per-doc (Gemini) -> status READY_FOR_REVIEW -> rebuild_bus_timetable.
Approval gates bot usage (only APPROVED docs surface in search). Drive OAuth is
injected (file_provider) so the ingest path is testable without Drive creds.
"""
from __future__ import annotations

import uuid
from typing import Awaitable, Callable

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector import vec_literal
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.models.user import User
from app.services.audit_service import record_audit

Embedder = Callable[[str], Awaitable[list[float]]]
FileProvider = Callable[[str], Awaitable[bytes]]


class KnowledgeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, doc_id: uuid.UUID) -> KnowledgeDocument | None:
        return await self.db.get(KnowledgeDocument, doc_id)

    async def upload(self, file_name: str, content: str, drive_file_id: str | None = None) -> KnowledgeDocument:
        doc = KnowledgeDocument(
            file_name=file_name, drive_file_id=drive_file_id, raw_text=content, status=KnowledgeStatus.UPLOADED
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

    async def process(self, embedder: Embedder, doc: KnowledgeDocument) -> KnowledgeDocument:
        """Embed 1 chunk-per-doc (whole content), mark READY_FOR_REVIEW, rebuild bus timetable."""
        doc.status = KnowledgeStatus.PROCESSING
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

    async def reindex(self, embedder: Embedder, doc: KnowledgeDocument) -> KnowledgeDocument:
        return await self.process(embedder, doc)

    async def search_test(self, embedder: Embedder, query: str, top_k: int = 10) -> list[dict]:
        emb = vec_literal(await embedder(query))
        rows = (
            await self.db.execute(
                text(
                    "SELECT c.content, 1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                    "FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id "
                    "WHERE d.status = 'APPROVED' AND c.embedding IS NOT NULL "
                    "ORDER BY c.embedding <=> CAST(:emb AS vector) LIMIT :k"
                ),
                {"emb": emb, "k": top_k},
            )
        ).all()
        return [{"content": r.content, "similarity": float(r.similarity)} for r in rows]

    async def list(self, *, status_: KnowledgeStatus | None = None) -> list[KnowledgeDocument]:
        q = select(KnowledgeDocument)
        if status_ is not None:
            q = q.where(KnowledgeDocument.status == status_)
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
