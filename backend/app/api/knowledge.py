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

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_embedder, require_admin
from app.core.db import get_db
from app.models.knowledge import KnowledgeStatus
from app.models.ingestion_template import KBIngestionRun
from app.models.user import User
from app.schemas.knowledge import (
    KBIngestResponse,
    KBTextFileListResponse,
    KBTextFileOut,
    KBVersionListResponse,
    KBVersionOut,
    KnowledgeChunkListResponse,
    KnowledgeChunkOut,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentOut,
    SearchTestRequest,
    SearchTestResult,
    UploadRequest,
)
from app.schemas.ingestion_templates import (
    AssignmentOut,
    AssignmentSet,
    IngestionRunOut,
    PreviewOut,
    PreviewRequest,
    TemplatePreviewRequest,
    TemplateCreate,
    TemplateOut,
    TemplateVersionOut,
    TemplateVersionUpdate,
    ReviewDecision,
)
from app.services.ingestion.template_compiler import TemplateCompileError
from app.services.ingestion.reference_templates import STARTER_PACKS
from app.services.ingestion.fact_repository import list_active_structured_facts
from app.services.audit_service import record_audit
from app.services.ingestion.template_ingestion import IngestionRunConflict, TemplateIngestionService
from app.services.ingestion.template_service import TemplateConflictError, TemplateService
from app.services.knowledge import KnowledgeFileExtractionError, KnowledgeService
from app.services.knowledge.canonical import (
    CanonicalValidationError,
    load_faq_template,
    load_template,
)
from app.workers.ingest_worker import enqueue_ingest, enqueue_ingest_version

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/ingestion-templates", response_model=list[TemplateOut])
async def list_ingestion_templates(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[TemplateOut]:
    return [TemplateOut.model_validate(item) for item in await TemplateService(db).list_templates()]


@router.get("/ingestion-template-starter-packs")
async def list_ingestion_template_starter_packs(
    _admin: User = Depends(require_admin),
) -> dict[str, dict]:
    return STARTER_PACKS


@router.post(
    "/ingestion-templates", response_model=TemplateVersionOut, status_code=status.HTTP_201_CREATED
)
async def create_ingestion_template(
    body: TemplateCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> TemplateVersionOut:
    try:
        _, version = await TemplateService(db).create_template(
            template_key=body.template_key,
            name=body.name,
            vertical=body.vertical,
            definition=body.definition,
            actor=admin,
        )
    except TemplateCompileError as exc:
        raise HTTPException(422, detail={"issues": exc.issues}) from exc
    except TemplateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    return TemplateVersionOut.model_validate(version)


@router.post("/ingestion-templates/preview", response_model=PreviewOut)
async def preview_new_ingestion_template(
    body: TemplatePreviewRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PreviewOut:
    try:
        checksum, records, issues = await TemplateIngestionService(db).preview(
            body.definition, body.source_text
        )
    except TemplateCompileError as exc:
        raise HTTPException(422, detail={"issues": exc.issues}) from exc
    return PreviewOut(checksum=checksum, records=records, issues=issues)


@router.get("/ingestion-templates/{template_id}/versions", response_model=list[TemplateVersionOut])
async def list_ingestion_template_versions(
    template_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateVersionOut]:
    try:
        versions = await TemplateService(db).list_versions(template_id)
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
    return [TemplateVersionOut.model_validate(item) for item in versions]


@router.post(
    "/ingestion-templates/{template_id}/drafts",
    response_model=TemplateVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def clone_ingestion_template_draft(
    template_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> TemplateVersionOut:
    try:
        version = await TemplateService(db).create_draft_from(template_id, actor=admin)
    except TemplateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    return TemplateVersionOut.model_validate(version)


@router.patch("/ingestion-template-versions/{version_id}", response_model=TemplateVersionOut)
async def update_ingestion_template_draft(
    version_id: uuid.UUID,
    body: TemplateVersionUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TemplateVersionOut:
    try:
        version = await TemplateService(db).update_draft(
            version_id, definition=body.definition, revision=body.revision, actor=admin
        )
    except TemplateCompileError as exc:
        raise HTTPException(422, detail={"issues": exc.issues}) from exc
    except TemplateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    return TemplateVersionOut.model_validate(version)


@router.post("/ingestion-template-versions/{version_id}/preview", response_model=PreviewOut)
async def preview_ingestion_template(
    version_id: uuid.UUID,
    body: PreviewRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PreviewOut:
    try:
        checksum, records, issues = await TemplateService(db).record_preview(
            version_id, source_text=body.source_text, actor=admin
        )
    except TemplateCompileError as exc:
        raise HTTPException(422, detail={"issues": exc.issues}) from exc
    except TemplateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    return PreviewOut(checksum=checksum, records=records, issues=issues)


@router.post("/ingestion-template-versions/{version_id}/publish", response_model=TemplateVersionOut)
async def publish_ingestion_template(
    version_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> TemplateVersionOut:
    try:
        version = await TemplateService(db).publish(version_id, actor=admin)
    except (TemplateConflictError, TemplateCompileError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return TemplateVersionOut.model_validate(version)


@router.post(
    "/ingestion-template-versions/{version_id}/deprecate", response_model=TemplateVersionOut
)
async def deprecate_ingestion_template(
    version_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> TemplateVersionOut:
    try:
        version = await TemplateService(db).deprecate(version_id, actor=admin)
    except TemplateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    return TemplateVersionOut.model_validate(version)


@router.get(
    "/projects/{project_id}/ingestion-template-assignment", response_model=AssignmentOut | None
)
async def get_ingestion_template_assignment(
    project_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> AssignmentOut | None:
    assignment = await TemplateService(db).current_assignment(project_id)
    return AssignmentOut.model_validate(assignment) if assignment else None


@router.put("/projects/{project_id}/ingestion-template-assignment", response_model=AssignmentOut)
async def set_ingestion_template_assignment(
    project_id: uuid.UUID,
    body: AssignmentSet,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AssignmentOut:
    try:
        assignment = await TemplateService(db).assign(
            project_id,
            template_version_id=body.template_version_id,
            revision=body.revision,
            actor=admin,
        )
    except TemplateConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    return AssignmentOut.model_validate(assignment)


@router.get("/ingestion-runs/{run_id}", response_model=IngestionRunOut)
async def get_ingestion_run(
    run_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> IngestionRunOut:
    run = await db.get(KBIngestionRun, run_id)
    if run is None:
        raise HTTPException(404, "ingestion run not found")
    return IngestionRunOut.model_validate(run)


@router.get(
    "/projects/{project_id}/kb/versions/{version_id}/ingestion-runs",
    response_model=list[IngestionRunOut],
)
async def list_kb_version_ingestion_runs(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[IngestionRunOut]:
    await KnowledgeService(db)._require_version(project_id, version_id)
    runs = list(
        (
            await db.scalars(
                select(KBIngestionRun)
                .where(KBIngestionRun.kb_version_id == version_id)
                .order_by(KBIngestionRun.attempt_no.desc())
            )
        ).all()
    )
    return [IngestionRunOut.model_validate(run) for run in runs]


@router.get("/projects/{project_id}/structured-facts")
async def list_project_structured_facts(
    project_id: uuid.UUID,
    record_type_key: str | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    facts = await list_active_structured_facts(
        db, project_id=project_id, record_type_key=record_type_key
    )
    return [
        {
            "id": str(fact.id),
            "record_type_key": fact.record_type_key,
            "payload": fact.payload,
            "evidence": fact.evidence,
            "scope_type": fact.scope_type,
            "scope_id": fact.scope_id,
        }
        for fact in facts
    ]


@router.post("/ingestion-runs/{run_id}/approve", response_model=IngestionRunOut)
async def approve_ingestion_run(
    run_id: uuid.UUID,
    body: ReviewDecision,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> IngestionRunOut:
    try:
        run = await TemplateIngestionService(db).approve(
            run_id, reviewer_id=admin.id, comment=body.comment
        )
    except IngestionRunConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return IngestionRunOut.model_validate(run)


@router.post("/ingestion-runs/{run_id}/reject", response_model=IngestionRunOut)
async def reject_ingestion_run(
    run_id: uuid.UUID,
    body: ReviewDecision,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> IngestionRunOut:
    try:
        run = await TemplateIngestionService(db).reject(
            run_id, reviewer_id=admin.id, comment=body.comment
        )
    except IngestionRunConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return IngestionRunOut.model_validate(run)


@router.get("/format/template", response_class=PlainTextResponse)
async def get_knowledge_format_template(
    kind: str = Query("knowledge", pattern="^(knowledge|faq)$"),
    _admin: User = Depends(require_admin),
) -> PlainTextResponse:
    if kind == "faq":
        return PlainTextResponse(
            load_faq_template(),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="vfic-faq-v1-template.md"'},
        )
    return PlainTextResponse(
        load_template(),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="vfic-knowledge-v1-template.md"'},
    )


@router.post(
    "/projects/{project_id}/kb/versions",
    response_model=KBVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_kb_version(
    project_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KBVersionOut:
    version = await KnowledgeService(db).create_version(project_id, actor=admin)
    await record_audit(
        db,
        action="kb_version_created",
        actor_id=admin.id,
        target_type="kb_version",
        target_id=str(version.id),
        payload={
            "project_id": str(project_id),
            "template_version_id": str(version.template_version_id),
        },
    )
    await db.commit()
    return KBVersionOut.model_validate(version)


@router.get("/projects/{project_id}/kb/versions", response_model=KBVersionListResponse)
async def list_kb_versions(
    project_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KBVersionListResponse:
    versions = await KnowledgeService(db).list_versions(project_id)
    return KBVersionListResponse(
        data=[KBVersionOut.model_validate(version) for version in versions],
        total=len(versions),
    )


@router.get(
    "/projects/{project_id}/kb/versions/{version_id}/files",
    response_model=KBTextFileListResponse,
)
async def list_kb_version_files(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KBTextFileListResponse:
    service = KnowledgeService(db)
    await service._require_version(project_id, version_id)
    files = await service.list_version_files(version_id)
    return KBTextFileListResponse(
        data=[KBTextFileOut.model_validate(file) for file in files],
        total=len(files),
    )


@router.post(
    "/projects/{project_id}/kb/versions/{version_id}/files",
    response_model=KBTextFileOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_kb_version_file(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KBTextFileOut:
    data = await file.read()
    try:
        uploaded = await KnowledgeService(db).upload_text_file(
            project_id=project_id,
            version_id=version_id,
            file_name=file.filename or "knowledge.md",
            content_type=file.content_type or "",
            data=data,
            actor=admin,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return KBTextFileOut.model_validate(uploaded)


@router.post(
    "/projects/{project_id}/kb/versions/{version_id}/ingest",
    response_model=KBIngestResponse,
)
async def ingest_kb_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KBIngestResponse:
    await KnowledgeService(db)._require_version(project_id, version_id)
    job_id = enqueue_ingest_version(version_id)
    await record_audit(
        db,
        action="kb_ingestion_enqueued",
        actor_id=admin.id,
        target_type="kb_version",
        target_id=str(version_id),
        payload={"project_id": str(project_id), "job_id": job_id},
    )
    await db.commit()
    return KBIngestResponse(job_id=job_id, status="PENDING", kb_version_id=version_id)


@router.post(
    "/projects/{project_id}/kb/versions/{version_id}/publish",
    response_model=KBVersionOut,
)
async def publish_kb_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KBVersionOut:
    try:
        version = await KnowledgeService(db).publish_version(project_id, version_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await record_audit(
        db,
        action="kb_version_published",
        actor_id=admin.id,
        target_type="kb_version",
        target_id=str(version_id),
        payload={"project_id": str(project_id), "manifest": version.release_manifest_sha256},
    )
    await db.commit()
    return KBVersionOut.model_validate(version)


@router.post("/projects/{project_id}/rag/test", response_model=list[SearchTestResult])
async def project_rag_test(
    project_id: uuid.UUID,
    body: SearchTestRequest,
    embedder=Depends(get_embedder),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SearchTestResult]:
    rows = await KnowledgeService(db).search_test(
        embedder, body.query, body.top_k, project_id=project_id
    )
    return [SearchTestResult(**row) for row in rows]


async def _load(doc_id: uuid.UUID, db: AsyncSession):
    doc = await KnowledgeService(db).get(doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
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
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
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
    doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(await _load(doc_id, db))


@router.get("/documents/{doc_id}/raw", response_class=PlainTextResponse)
async def download_raw_document(
    doc_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
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
        doc.raw_text or "",
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
    result = await service.update(await _load(doc_id, db), body, actor=admin)
    return KnowledgeDocumentOut.model_validate(result)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> None:
    service = KnowledgeService(db)
    await service.delete(await _load(doc_id, db), actor=admin)


@router.post(
    "/documents/upload", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED
)
async def upload(
    body: UploadRequest, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
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
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentOut:
    """Multipart upload: extract text, store original, enqueue the training pipeline."""
    data = await file.read()
    try:
        doc = await KnowledgeService(db).upload_bytes(
            file.filename or "upload",
            file.content_type or "",
            data,
            project_id=project_id,
            require_canonical=True,
        )
    except CanonicalValidationError as exc:
        raise HTTPException(422, {"errors": exc.errors}) from exc
    except KnowledgeFileExtractionError as exc:
        raise HTTPException(422, {"errors": [str(exc)]}) from exc
    await record_audit_safe(db, "upload_knowledge", _admin.id, str(doc.id))
    enqueue_ingest(doc.id)  # async LLM digest -> embed -> index
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/documents/{doc_id}/process", response_model=KnowledgeDocumentOut)
async def process(
    doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> KnowledgeDocumentOut:
    """(Re)run the async LLM training pipeline for a document."""
    doc = await _load(doc_id, db)
    enqueue_ingest(doc.id)
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/documents/{doc_id}/archive", response_model=KnowledgeDocumentOut)
async def archive(
    doc_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut.model_validate(
        await KnowledgeService(db).archive(await _load(doc_id, db), actor=admin)
    )


@router.post("/documents/{doc_id}/reindex", response_model=KnowledgeDocumentOut)
async def reindex(
    doc_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> KnowledgeDocumentOut:
    doc = await _load(doc_id, db)
    enqueue_ingest(doc.id)
    return KnowledgeDocumentOut.model_validate(doc)


@router.post("/search-test", response_model=list[SearchTestResult])
async def search_test(
    body: SearchTestRequest,
    embedder=Depends(get_embedder),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SearchTestResult]:
    rows = await KnowledgeService(db).search_test(
        embedder, body.query, body.top_k, project_id=body.project_id
    )
    return [SearchTestResult(**r) for r in rows]


async def record_audit_safe(
    db: AsyncSession, action: str, actor_id: uuid.UUID, target_id: str
) -> None:
    from app.services.audit_service import record_audit

    await record_audit(
        db, action=action, actor_id=actor_id, target_type="knowledge_document", target_id=target_id
    )
    await db.commit()
