"""Recruitment knowledge-project admin API — thin HTTP layer over :class:`ProjectService`.

All CRUD, master-index rebuild, and worker knowledge-feature CRUD/re-extraction live
in ``app.services.project``; this router only validates input, delegates, and
serializes the response. Domain exceptions raised by the service are mapped to HTTP
status codes.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_admin, require_recruiter
from app.project_knowledge.infrastructure.api_dependencies import get_project_knowledge_db
from app.schemas.projects import (
    BusTimetableResponse,
    FeatureListResponse,
    FeatureOut,
    FeatureUpdate,
    ProjectFaqCreate,
    ProjectFaqOut,
    ProjectFaqResponse,
    ProjectFaqUpdate,
    ProjectCreate,
    ProjectListResponse,
    ProjectOut,
    ProjectUpdate,
)
from app.schemas.knowledge_bases import (
    DirectContextFileDetailOut,
    DirectContextFileOut,
    DirectContextFileUpsert,
)
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.schemas.project_knowledge import (
    CategoryCatalogOut,
    CategoryAuthorityOut,
    CategoryCutoverRequest,
    CategoryClearRequest,
    CategoryReplaceOut,
    CategoryReplaceRequest,
    CategoryRollbackRequest,
    CategoryRevisionOut,
    CategorySourceOut,
    CategoryTemplateOut,
)
from app.schemas.project_single_page_sync import (
    SinglePageExternalSourceCreate,
    SinglePageExternalSourceOut,
)
from app.services.knowledge.category_contracts import (
    get_category_definition,
    load_category_template,
)
from app.composition.project_knowledge import build_category_use_cases
from app.services.project import ProjectService
from app.shared.domain.errors import BadRequestError, ConflictError, RateLimitedError

router = APIRouter(prefix="/knowledge/projects", tags=["projects"])
_SINGLE_PAGE_SOURCE_BAD_REQUESTS = {
    "conflicting_gid",
    "host_not_allowed",
    "invalid_gid",
    "invalid_sheet_id",
    "invalid_url",
    "ip_literal_forbidden",
    "missing_gid",
    "scheme_not_https",
    "unsafe_gid",
    "url_credentials_forbidden",
}


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    is_active: bool | None = Query(None),
    q: str | None = Query(
        None, description="Case-insensitive search over project name, slug, summary"
    ),
    sort: str | None = Query(
        None, description="Sort field (name, created_at, updated_at, is_active)"
    ),
    order: str | None = Query("desc", description="Sort direction: asc | desc"),
    _user: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> ProjectListResponse:
    data, total = await ProjectService(db).list_with_readiness(
        is_active,
        page=page,
        per_page=per_page,
        sort_by=sort,
        order=order,
        q=q,
    )
    return ProjectListResponse(data=data, total=total)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    _user: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> ProjectOut:
    return await ProjectService(db).get_with_readiness(project_id)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> ProjectOut:
    project = await ProjectService(db).create(body, admin)
    return await ProjectService(db).get_with_readiness(project.id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    actor: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> ProjectOut:
    project = await ProjectService(db).update(project_id, body, actor)
    return await ProjectService(db).get_with_readiness(project.id)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> None:
    await ProjectService(db).delete(project_id, admin)


@router.get("/{project_id}/single-page", response_model=DirectContextFileDetailOut)
async def get_project_single_page(
    project_id: uuid.UUID,
    _user: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> DirectContextFileDetailOut:
    direct_file = await ProjectService(db).get_single_page(project_id)
    return DirectContextFileDetailOut(
        **DirectContextFileOut.model_validate(direct_file).model_dump(),
        text=direct_file.raw_text,
    )


@router.put("/{project_id}/single-page", response_model=DirectContextFileOut)
async def replace_project_single_page(
    project_id: uuid.UUID,
    body: DirectContextFileUpsert,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> DirectContextFileOut:
    direct_file = await ProjectService(db).replace_single_page(project_id, body, admin)
    return DirectContextFileOut.model_validate(direct_file)


@router.get(
    "/{project_id}/single-page/external-sources",
    response_model=list[SinglePageExternalSourceOut],
)
async def list_project_single_page_external_sources(
    project_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> list[SinglePageExternalSourceOut]:
    rows = await ProjectService(db).list_single_page_external_sources(project_id)
    return [SinglePageExternalSourceOut.model_validate(row) for row in rows]


@router.post(
    "/{project_id}/single-page/external-sources",
    response_model=SinglePageExternalSourceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_single_page_external_source(
    project_id: uuid.UUID,
    body: SinglePageExternalSourceCreate,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> SinglePageExternalSourceOut:
    try:
        row = await ProjectService(db).create_single_page_external_source(project_id, body, admin)
    except ConflictError as exc:
        if str(exc) in _SINGLE_PAGE_SOURCE_BAD_REQUESTS:
            raise BadRequestError(str(exc)) from exc
        raise
    return SinglePageExternalSourceOut.model_validate(row)


@router.post("/{project_id}/single-page/external-sources/{source_id}/run-now")
async def run_project_single_page_external_source_now(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> dict[str, str]:
    try:
        job_id = await ProjectService(db).run_single_page_external_source_now(
            project_id, source_id, admin
        )
    except ConflictError as exc:
        if str(exc) == "run_now_cooldown":
            raise RateLimitedError("run_now_cooldown") from exc
        raise
    return {"job_id": job_id}


@router.delete(
    "/{project_id}/single-page/external-sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_single_page_external_source(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> None:
    await ProjectService(db).delete_single_page_external_source(project_id, source_id, admin)


@router.get("/{project_id}/categories", response_model=CategoryCatalogOut)
async def list_project_categories(
    project_id: uuid.UUID,
    _user: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> CategoryCatalogOut:
    data = await build_category_use_cases(db).list_catalog(project_id)
    return CategoryCatalogOut(data=data, total=len(data))


@router.get(
    "/{project_id}/categories/{category_key}/template",
    response_model=CategoryTemplateOut,
)
async def get_project_category_template(
    project_id: uuid.UUID,
    category_key: KnowledgeCategoryKey,
    _user: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> CategoryTemplateOut:
    await build_category_use_cases(db).list_catalog(project_id)
    definition = get_category_definition(category_key)
    return CategoryTemplateOut(
        key=category_key,
        label_vi=definition.label_vi,
        filename=definition.template_filename,
        content=load_category_template(category_key),
    )


@router.get(
    "/{project_id}/categories/{category_key}",
    response_model=CategorySourceOut,
)
async def get_project_category_source(
    project_id: uuid.UUID,
    category_key: KnowledgeCategoryKey,
    _user: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> CategorySourceOut:
    return await build_category_use_cases(db).get_active_source(project_id, category_key)


@router.put(
    "/{project_id}/categories/{category_key}",
    response_model=CategoryReplaceOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replace_project_category(
    project_id: uuid.UUID,
    category_key: KnowledgeCategoryKey,
    body: CategoryReplaceRequest,
    editor: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> CategoryReplaceOut:
    revision, job_id = await build_category_use_cases(db).stage_replacement(
        project_id=project_id,
        category_key=category_key,
        filename=body.filename,
        source_yaml=body.content,
        actor=editor,
    )
    return CategoryReplaceOut(
        revision=CategoryRevisionOut.model_validate(revision),
        job_id=job_id,
    )


@router.post(
    "/{project_id}/categories/{category_key}/upload",
    response_model=CategoryReplaceOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_project_category(
    project_id: uuid.UUID,
    category_key: KnowledgeCategoryKey,
    file: UploadFile = File(...),
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> CategoryReplaceOut:
    filename = file.filename or f"{category_key.value}.yaml"
    if not filename.lower().endswith((".yaml", ".yml")):
        from app.shared.domain.errors import ConflictError

        raise ConflictError("RAG category uploads accept only .yaml or .yml files")
    raw = await file.read(500_001)
    if len(raw) > 500_000:
        from app.shared.domain.errors import ConflictError

        raise ConflictError("Category YAML exceeds the 500 KB limit")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        from app.shared.domain.errors import ConflictError

        raise ConflictError("Category YAML must use UTF-8 encoding") from exc
    revision, job_id = await build_category_use_cases(db).stage_replacement(
        project_id=project_id,
        category_key=category_key,
        filename=filename,
        source_yaml=content,
        actor=admin,
    )
    return CategoryReplaceOut(
        revision=CategoryRevisionOut.model_validate(revision),
        job_id=job_id,
    )


@router.post(
    "/{project_id}/categories/{category_key}/clear",
    response_model=CategoryRevisionOut,
)
async def clear_project_category(
    project_id: uuid.UUID,
    category_key: KnowledgeCategoryKey,
    _body: CategoryClearRequest,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> CategoryRevisionOut:
    revision = await build_category_use_cases(db).clear(
        project_id=project_id,
        category_key=category_key,
        actor=admin,
    )
    return CategoryRevisionOut.model_validate(revision)


@router.post("/{project_id}/categories/cutover", response_model=CategoryAuthorityOut)
async def cutover_project_categories(
    project_id: uuid.UUID,
    _body: CategoryCutoverRequest,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> CategoryAuthorityOut:
    project = await build_category_use_cases(db).cutover_category_authority(
        project_id=project_id,
        actor=admin,
    )
    return CategoryAuthorityOut(
        project_id=project.id,
        category_authority_started=project.category_authority_started,
        category_cutover_at=project.category_cutover_at,
    )


@router.post("/{project_id}/categories/rollback", response_model=CategoryAuthorityOut)
async def rollback_project_categories(
    project_id: uuid.UUID,
    _body: CategoryRollbackRequest,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> CategoryAuthorityOut:
    project = await build_category_use_cases(db).rollback_category_authority(
        project_id=project_id,
        actor=admin,
    )
    return CategoryAuthorityOut(
        project_id=project.id,
        category_authority_started=project.category_authority_started,
        category_cutover_at=project.category_cutover_at,
    )


@router.post("/{project_id}/reindex", response_model=ProjectOut)
async def reindex_project(
    project_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(db).reindex(project_id))


@router.get("/{project_id}/features", response_model=FeatureListResponse)
async def list_project_features(
    project_id: uuid.UUID,
    _user: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> FeatureListResponse:
    """List the project's active extracted worker product features (catalog order)."""
    return await ProjectService(db).list_features(project_id)


@router.get("/{project_id}/bus-timetable", response_model=BusTimetableResponse)
async def list_project_bus_timetable(
    project_id: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(6, ge=1, le=25),
    _user: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> BusTimetableResponse:
    """List the project's structured bus routes with ordered pickup stops."""
    return await ProjectService(db).list_bus_timetable(project_id, page=page, per_page=per_page)


@router.get("/{project_id}/faq", response_model=ProjectFaqResponse)
async def list_project_faq(
    project_id: uuid.UUID,
    limit: int = Query(12, ge=1, le=50),
    _user: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> ProjectFaqResponse:
    """List the project's published FAQ answers."""
    return await ProjectService(db).list_faq(project_id, limit=limit)


@router.post(
    "/{project_id}/faq",
    response_model=ProjectFaqOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_faq(
    project_id: uuid.UUID,
    body: ProjectFaqCreate,
    actor: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> ProjectFaqOut:
    """Create a question/answer pair in the project's FAQ knowledge."""
    raise ConflictError("FAQ is read-only here; update the Project FAQ YAML category")


@router.patch("/{project_id}/faq/{faq_id}", response_model=ProjectFaqOut)
async def update_project_faq(
    project_id: uuid.UUID,
    faq_id: uuid.UUID,
    body: ProjectFaqUpdate,
    actor: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> ProjectFaqOut:
    """Edit a question/answer pair in the project's FAQ knowledge."""
    raise ConflictError("FAQ is read-only here; update the Project FAQ YAML category")


@router.delete("/{project_id}/faq/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_faq(
    project_id: uuid.UUID,
    faq_id: uuid.UUID,
    actor: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> None:
    """Delete a question/answer pair from the project's FAQ knowledge."""
    raise ConflictError("FAQ is read-only here; clear or replace the Project FAQ YAML category")


@router.patch("/{project_id}/features/{feature_id}", response_model=FeatureOut)
async def update_project_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    body: FeatureUpdate,
    actor: Any = Depends(require_recruiter),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> FeatureOut:
    """Recruiter/admin review-edit of one feature value; re-syncs product highlights."""
    raise ConflictError("Project features are read-only projections of category YAML")


@router.post("/{project_id}/features/extract", response_model=FeatureListResponse)
async def extract_project_features(
    project_id: uuid.UUID,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> FeatureListResponse:
    """Synchronously re-extract active product features from the project's latest posting."""
    raise ConflictError("Project features are read-only projections of category YAML")
