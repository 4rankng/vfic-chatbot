"""Knowledge admin API: upload/process/archive/reindex/search-test/list.

Two upload routes:
  * ``POST /documents/upload``       — JSON text upload (programmatic / legacy). No training.
  * ``POST /documents/upload-file``  — multipart file upload (Office/PDF/text). Extracts text,
                                       persists the original, then enqueues the async LLM
                                       training pipeline on the ``ingest`` queue.
``process`` / ``reindex`` enqueue the same async pipeline. Pipeline progress is read back
via ``GET /documents/{id}`` (``stage`` / ``digest_meta`` / ``error``).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.knowledge import KnowledgeStatus
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeChunkListResponse,
    KnowledgeChunkOut,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentOut,
    SearchTestRequest,
    SearchTestResult,
    UploadRequest,
)
from app.services.knowledge_service import KnowledgeService
from app.workers.ingest_worker import enqueue_ingest

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


async def _load(doc_id: uuid.UUID, db: AsyncSession):
    doc = await KnowledgeService(db).get(doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return doc


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
async def list_documents(
    status_: KnowledgeStatus | None = Query(None, alias="status"),
    project_id: uuid.UUID | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentListResponse:
    docs = await KnowledgeService(db).list(status_=status_, project_id=project_id)
    return KnowledgeDocumentListResponse(data=[KnowledgeDocumentOut.model_validate(d) for d in docs], total=len(docs))


@router.get("/documents/{doc_id}", response_model=KnowledgeDocumentOut)
async def get_document(
    doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(await _load(doc_id, db))


@router.get("/documents/{doc_id}/chunks", response_model=KnowledgeChunkListResponse)
async def list_document_chunks(
    doc_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeChunkListResponse:
    await _load(doc_id, db)
    rows = await KnowledgeService(db).list_chunks(doc_id, limit=limit)
    return KnowledgeChunkListResponse(
        data=[KnowledgeChunkOut.model_validate(row) for row in rows],
        total=len(rows),
    )


@router.patch("/documents/{doc_id}", response_model=KnowledgeDocumentOut)
async def update_document(
    doc_id: uuid.UUID,
    body: KnowledgeDocumentUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentOut:
    service = KnowledgeService(db)
    return KnowledgeDocumentOut.model_validate(await service.update(await _load(doc_id, db), body, actor=admin))


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> None:
    service = KnowledgeService(db)
    await service.delete(await _load(doc_id, db), actor=admin)


@router.post("/documents/upload", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload(body: UploadRequest, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    doc = await KnowledgeService(db).upload(body.file_name, body.content, body.drive_file_id, body.project_id)
    await record_audit_safe(db, "upload_knowledge", _admin.id, str(doc.id))
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/documents/upload-file", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    project_id: uuid.UUID | None = Form(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentOut:
    """Multipart upload: extract text, store original, enqueue the training pipeline."""
    data = await file.read()
    doc = await KnowledgeService(db).upload_bytes(
        file.filename or "upload", file.content_type or "", data, project_id=project_id
    )
    await record_audit_safe(db, "upload_knowledge", _admin.id, str(doc.id))
    enqueue_ingest(doc.id)  # async LLM digest -> embed -> index
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/documents/{doc_id}/process", response_model=KnowledgeDocumentOut)
async def process(doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    """(Re)run the async LLM training pipeline for a document."""
    doc = await _load(doc_id, db)
    enqueue_ingest(doc.id)
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/documents/{doc_id}/archive", response_model=KnowledgeDocumentOut)
async def archive(doc_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(await KnowledgeService(db).archive(await _load(doc_id, db), actor=admin))


@router.post("/documents/{doc_id}/reindex", response_model=KnowledgeDocumentOut)
async def reindex(doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> KnowledgeDocumentOut:
    doc = await _load(doc_id, db)
    enqueue_ingest(doc.id)
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/search-test", response_model=list[SearchTestResult])
async def search_test(body: SearchTestRequest, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[SearchTestResult]:
    from app.graph.clients import GeminiEmbedder

    rows = await KnowledgeService(db).search_test(GeminiEmbedder(), body.query, body.top_k, project_id=body.project_id)
    return [SearchTestResult(**r) for r in rows]


async def record_audit_safe(db: AsyncSession, action: str, actor_id: uuid.UUID, target_id: str) -> None:
    from app.services.audit_service import record_audit

    await record_audit(db, action=action, actor_id=actor_id, target_type="knowledge_document", target_id=target_id)
    await db.commit()
