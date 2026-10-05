"""Knowledge admin API: upload/process/archive/reindex/search-test/list.

Two upload routes:
  * ``POST /documents/upload``       — JSON text upload (programmatic / legacy). No training.
  * ``POST /documents/upload-file``  — multipart file upload (DOCX/Markdown/text). Extracts text,
                                       persists the original, then enqueues the async LLM
                                       training pipeline on the ``ingest`` queue.
``process`` / ``reindex`` enqueue the same async pipeline. Pipeline progress is read back
via ``GET /documents/{id}`` (``stage`` / ``digest_meta`` / ``error``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_admin
from app.api.provider_dependencies import get_embedder
from app.project_knowledge.infrastructure.api_dependencies import get_project_knowledge_db
from app.project_knowledge.domain.legacy_job_references import strip_legacy_job_reference_source
from app.schemas.knowledge import (
    KnowledgeChunkListResponse,
    KnowledgeChunkOut,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentOut,
    ProjectTrainingPlan,
    KnowledgeStatus,
    SearchTestRequest,
    SearchTestResult,
    UploadRequest,
)
from app.services.audit_service import record_audit
from app.services.ingestion.limits import read_upload_within_limit
from app.services.knowledge import KnowledgeFileExtractionError, KnowledgeService
from app.services.knowledge.canonical import (
    CanonicalValidationError,
)
from app.shared.domain.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.shared.infrastructure.rate_limits import enforce_rag_test_rate_limit
from app.composition.project_knowledge_jobs import build_project_knowledge_jobs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
_project_knowledge_jobs = build_project_knowledge_jobs()


@router.post("/projects/{project_id}/rag/test", response_model=list[SearchTestResult])
async def project_rag_test(
    project_id: uuid.UUID,
    body: SearchTestRequest,
    embedder=Depends(get_embedder),
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> list[SearchTestResult]:
    # Every call spends an embedding request; a per-user cap keeps one admin from
    # draining the deployment-wide embed token list (SEC-04).
    await enforce_rag_test_rate_limit(_admin.id)
    rows = await KnowledgeService(db).search_test(
        embedder, body.query, body.top_k, project_id=project_id
    )
    return [SearchTestResult(**row) for row in rows]


async def _load(doc_id: uuid.UUID, db: AsyncSession):
    doc = await KnowledgeService(db).get(doc_id)
    if doc is None:
        raise NotFoundError("document not found")
    return doc


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    status_: KnowledgeStatus | None = Query(None, alias="status"),
    project_id: uuid.UUID | None = Query(None),
    stage: str | None = Query(None),
    needs_review: bool | None = Query(None),
    q: str | None = Query(
        None, description="Case-insensitive search over source metadata and project name"
    ),
    sort: str | None = Query(
        None, description="Sort field (updated_at, created_at, file_name, stage, status)"
    ),
    order: str | None = Query("desc", description="Sort direction: asc | desc"),
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeDocumentListResponse:
    docs, total = await KnowledgeService(db).list(
        page=page,
        per_page=per_page,
        status_=status_,
        project_id=project_id,
        stage=stage,
        needs_review=needs_review,
        q=q,
        sort_by=sort,
        order=order,
    )
    return KnowledgeDocumentListResponse(
        data=[KnowledgeDocumentOut.model_validate(d) for d in docs], total=total
    )


@router.get("/documents/{doc_id}", response_model=KnowledgeDocumentOut)
async def get_document(
    doc_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(await _load(doc_id, db))


@router.get("/documents/{doc_id}/raw", response_class=PlainTextResponse)
async def download_raw_document(
    doc_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> PlainTextResponse:
    doc = await _load(doc_id, db)
    filename = (
        (doc.file_name or "knowledge-source.md")
        .replace('"', "")
        .replace("/", "-")
        .replace("\\", "-")
    )
    if "." not in filename:
        filename = f"{filename}.md"
    fallback_filename = filename.encode("ascii", "ignore").decode() or "knowledge-source.md"
    return PlainTextResponse(
        strip_legacy_job_reference_source(doc.raw_text or ""),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{fallback_filename}\"; filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/documents/{doc_id}/chunks", response_model=KnowledgeChunkListResponse)
async def list_document_chunks(
    doc_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
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
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeDocumentOut:
    service = KnowledgeService(db)
    result = await service.update(await _load(doc_id, db), body, actor=admin)
    return KnowledgeDocumentOut.model_validate(result)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> None:
    service = KnowledgeService(db)
    await service.delete(await _load(doc_id, db), actor=admin)


@router.post(
    "/documents/upload", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED
)
async def upload(
    body: UploadRequest,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeDocumentOut:
    doc = await KnowledgeService(db).upload(
        body.file_name, body.content, body.drive_file_id, body.project_id
    )
    await record_audit_safe(db, "upload_knowledge", _admin.id, str(doc.id))
    return KnowledgeDocumentOut.model_validate(doc)


@router.post(
    "/documents/upload-file",
    response_model=KnowledgeDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    file: UploadFile = File(...),
    project_id: uuid.UUID | None = Form(None),
    category_plan: str | None = Form(None, max_length=2_000_000),
    auto_extract: bool = Form(False),
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeDocumentOut:
    """Multipart upload: extract text, store original, enqueue the training pipeline.

    ``auto_extract`` retains the source and queues complete category extraction.
    Provider work runs on the ingest worker and is resumable from that source.
    """
    data = await read_upload_within_limit(file)
    plan = None
    if category_plan is not None:
        try:
            plan = ProjectTrainingPlan.model_validate_json(category_plan)
        except ValueError as exc:
            raise ValidationError("Kế hoạch nạp danh mục chưa hợp lệ. Vui lòng kiểm tra tệp rồi thử lại.") from exc
    try:
        doc = await KnowledgeService(db).upload_bytes(
            file.filename or "upload",
            file.content_type or "",
            data,
            project_id=project_id,
            training_plan=plan,
            auto_extract=auto_extract and plan is None,
            actor=_admin,
        )
    except CanonicalValidationError as exc:
        logger.warning(
            "knowledge upload rejected project=%s file=%s errors=%s",
            project_id,
            file.filename,
            exc.errors,
        )
        raise ValidationError({"errors": exc.errors}) from exc
    except KnowledgeFileExtractionError as exc:
        logger.warning(
            "knowledge upload extraction failed project=%s file=%s cause=%s",
            project_id,
            file.filename,
            exc,
        )
        raise ValidationError({"errors": [str(exc)]}) from exc
    await record_audit_safe(db, "upload_knowledge", _admin.id, str(doc.id))
    await _queue_document(doc, db, reuse_completed=True)
    return KnowledgeDocumentOut.model_validate(doc)


async def _queue_document(doc, db, *, reuse_completed=False) -> None:
    await KnowledgeService(db).queue_document(
        doc, jobs=_project_knowledge_jobs, reuse_completed=reuse_completed,
    )


@router.post("/documents/{doc_id}/process", response_model=KnowledgeDocumentOut)
async def process(
    doc_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeDocumentOut:
    """(Re)run the async LLM training pipeline for a document."""
    doc = await _load(doc_id, db)
    await KnowledgeService(db).assert_source_reprocessable(doc)
    await _queue_document(doc, db)
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/documents/{doc_id}/archive", response_model=KnowledgeDocumentOut)
async def archive(
    doc_id: uuid.UUID,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(
        await KnowledgeService(db).archive(await _load(doc_id, db), actor=admin)
    )


@router.post("/documents/{doc_id}/reindex", response_model=KnowledgeDocumentOut)
async def reindex(
    doc_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeDocumentOut:
    doc = await _load(doc_id, db)
    await KnowledgeService(db).assert_source_reprocessable(doc)
    await _queue_document(doc, db)
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/reindex-all")
async def reindex_all(
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> dict:
    """Re-queue every RAG knowledge source for authoritative rebuilding.

    The offline pipeline refreshes chunks and all structured projections,
    including the KB-authoritative active-job catalog.
    """
    queued = await KnowledgeService(db).reindex_all(admin)
    return {"status": "ok", "queued": queued}


@router.post("/search-test", response_model=list[SearchTestResult])
async def search_test(
    body: SearchTestRequest,
    embedder=Depends(get_embedder),
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> list[SearchTestResult]:
    rows = await KnowledgeService(db).search_test(
        embedder, body.query, body.top_k, project_id=body.project_id
    )
    return [SearchTestResult(**r) for r in rows]


async def record_audit_safe(
    db: AsyncSession, action: str, actor_id: uuid.UUID, target_id: str
) -> None:

    await record_audit(
        db, action=action, actor_id=actor_id, target_type="knowledge_document", target_id=target_id
    )
    await db.commit()
