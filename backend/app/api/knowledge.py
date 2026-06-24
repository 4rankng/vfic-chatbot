"""Knowledge admin API: upload/process/approve/reject/archive/reindex/search-test/list."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.knowledge import KnowledgeStatus
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeDocumentListResponse,
    KnowledgeDocumentOut,
    SearchTestRequest,
    SearchTestResult,
    UploadRequest,
)
from app.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


async def _load(doc_id: uuid.UUID, db: AsyncSession):
    doc = await KnowledgeService(db).get(doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return doc


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
async def list_documents(
    status_: KnowledgeStatus | None = Query(None, alias="status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentListResponse:
    docs = await KnowledgeService(db).list(status_=status_)
    return KnowledgeDocumentListResponse(data=[KnowledgeDocumentOut.model_validate(d) for d in docs], total=len(docs))


@router.get("/documents/{doc_id}", response_model=KnowledgeDocumentOut)
async def get_document(
    doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(await _load(doc_id, db))


@router.post("/documents/upload", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload(body: UploadRequest, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    doc = await KnowledgeService(db).upload(body.file_name, body.content, body.drive_file_id)
    await record_audit_safe(db, "upload_knowledge", _admin.id, str(doc.id))
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/documents/{doc_id}/process", response_model=KnowledgeDocumentOut)
async def process(doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    doc = await _load(doc_id, db)
    from app.graph.llm_real import GeminiEmbedder  # lazy: only real runs need Gemini

    await KnowledgeService(db).process(GeminiEmbedder(), doc)
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/documents/{doc_id}/approve", response_model=KnowledgeDocumentOut)
async def approve(doc_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(await KnowledgeService(db).approve(await _load(doc_id, db), actor=admin))


@router.post("/documents/{doc_id}/reject", response_model=KnowledgeDocumentOut)
async def reject(doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(await KnowledgeService(db).reject(await _load(doc_id, db)))


@router.post("/documents/{doc_id}/archive", response_model=KnowledgeDocumentOut)
async def archive(doc_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(await KnowledgeService(db).archive(await _load(doc_id, db), actor=admin))


@router.post("/documents/{doc_id}/reindex", response_model=KnowledgeDocumentOut)
async def reindex(doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    doc = await _load(doc_id, db)
    from app.graph.llm_real import GeminiEmbedder

    await KnowledgeService(db).reindex(GeminiEmbedder(), doc)
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/search-test", response_model=list[SearchTestResult])
async def search_test(body: SearchTestRequest, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[SearchTestResult]:
    from app.graph.llm_real import GeminiEmbedder

    rows = await KnowledgeService(db).search_test(GeminiEmbedder(), body.query, body.top_k)
    return [SearchTestResult(**r) for r in rows]


async def record_audit_safe(db: AsyncSession, action: str, actor_id: uuid.UUID, target_id: str) -> None:
    from app.services.audit_service import record_audit

    await record_audit(db, action=action, actor_id=actor_id, target_type="knowledge_document", target_id=target_id)
    await db.commit()
