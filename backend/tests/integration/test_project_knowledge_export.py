"""Real publication, lifecycle and scope proof for saved-knowledge downloads."""

import hashlib
import uuid

import pytest
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.company import Project
from app.models.knowledge import (
    KBTextFile,
    KBVersion,
    KBVersionStatus,
    KnowledgeBase,
    KnowledgeBaseDirectFile,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.services.project import ProjectService
from app.shared.domain.errors import ConflictError, NotFoundError

pytestmark = pytest.mark.integration


async def _project(db, *, mode=KnowledgeBaseMode.RAG, authority=True, reverse_owner=True):
    project = Project(
        slug="export-" + uuid.uuid4().hex[:12],
        name="Xưởng Hải Phòng",
        is_active=False,
        category_authority_started=authority,
        external_api={"credential": "NEVER_EXPORT_RUNTIME_CREDENTIAL"},
    )
    db.add(project)
    await db.flush()
    base = KnowledgeBase(
        name=project.name,
        slug=project.slug,
        mode=mode,
        project_id=project.id if reverse_owner else None,
    )
    db.add(base)
    await db.flush()
    project.knowledge_base_id = base.id
    await db.flush()
    return project, base


async def _direct(db, base, source="\n  Lương 6.000.000 đồng.\n\n"):
    file = KnowledgeBaseDirectFile(
        knowledge_base_id=base.id,
        filename="thong-tin.txt",
        raw_text=source,
        normalized_text="DIFFERENT_NORMALIZED_SOURCE",
        content_sha256="a" * 64,
        char_count=len(source),
        line_count=source.count("\n") + 1,
    )
    db.add(file)
    await db.flush()
    return file


async def _category(
    db,
    project,
    key,
    source,
    *,
    status=KnowledgeCategoryRevisionStatus.ACTIVE,
    document_status=KnowledgeStatus.PUBLISHED,
    pointed=True,
    document_owner=None,
):
    category = KnowledgeCategory(project_id=project.id, category_key=key)
    db.add(category)
    await db.flush()
    revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=1,
        status=status,
        source_filename=f"{key}.md",
        source_markdown=source,
        normalized_payload={"private": "NEVER_EXPORT_NORMALIZED_PAYLOAD"},
        content_sha256="b" * 64,
    )
    db.add(revision)
    await db.flush()
    doc = KnowledgeDocument(
        project_id=document_owner or project.id,
        category_revision_id=revision.id,
        file_name=f"{key}.md",
        status=document_status,
        raw_text="NEVER_EXPORT_DOCUMENT_TEXT_INSTEAD_OF_CATEGORY",
        digest_meta={"private": "NEVER_EXPORT_DOCUMENT_METADATA"},
    )
    db.add(doc)
    if pointed:
        category.active_revision_id = revision.id
    await db.flush()
    return category, revision, doc


async def _version(db, project, *, number=1, status=KBVersionStatus.ACTIVE, pointed=True):
    version = KBVersion(project_id=project.id, version_no=number, status=status)
    db.add(version)
    await db.flush()
    if pointed:
        project.active_kb_version_id = version.id
    await db.flush()
    return version


async def _legacy(
    db,
    project,
    version,
    source,
    *,
    status=KnowledgeStatus.PUBLISHED,
    document_owner=None,
    file_owner=None,
    linked=True,
):
    doc = KnowledgeDocument(
        project_id=document_owner or project.id,
        file_name="legacy.md",
        status=status,
        raw_text="NEVER_EXPORT_DOCUMENT_TEXT_INSTEAD_OF_SAVED_FILE",
    )
    db.add(doc)
    await db.flush()
    file = KBTextFile(
        project_id=file_owner or project.id,
        kb_version_id=version.id,
        document_id=doc.id if linked else None,
        filename="legacy.md",
        raw_text="OLD_UNREPAIRED_UPLOAD",
        normalized_text=source,
        content_sha256=hashlib.sha256(source.encode()).hexdigest(),
        char_count=len(source),
        line_count=source.count("\n") + 1,
    )
    db.add(file)
    await db.flush()
    return file, doc


async def test_direct_export_uses_exact_saved_text_and_no_stale_rag_or_metadata(
    integration_session,
):
    db = integration_session
    project, base = await _project(db, mode=KnowledgeBaseMode.DIRECT_CONTEXT)
    source = "\n  Nhà máy tuyển công nhân.\nLương 6.000.000 đồng.\n\n"
    await _direct(db, base, source)
    await _category(db, project, "jobs", "STALE_CATEGORY_MUST_NOT_LEAK")
    version = await _version(db, project)
    await _legacy(db, project, version, "STALE_LEGACY_MUST_NOT_LEAK")

    exported = await ProjectService(db).export_knowledge(project.id)

    assert source in exported.content
    assert "NEVER_EXPORT" not in exported.content
    assert "STALE_" not in exported.content
    assert "OLD_UNREPAIRED" not in exported.content
    assert exported.filename == f"kb-{project.slug}.md"


async def test_category_export_follows_active_pointers_in_canonical_order(integration_session):
    db = integration_session
    project, _base = await _project(db)
    await _category(db, project, "compensation", "  ACTIVE_PAY\n\n")
    jobs, _revision, _doc = await _category(db, project, "jobs", "\nACTIVE_JOBS\n")
    staged = KnowledgeCategoryRevision(
        category_id=jobs.id,
        revision_no=2,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="draft.md",
        source_markdown="UNPUBLISHED_REPLACEMENT",
        normalized_payload={},
        content_sha256="d" * 64,
    )
    db.add(staged)
    await db.flush()
    version = await _version(db, project)
    await _legacy(db, project, version, "LEGACY_BEFORE_CUTOVER")

    exported = await ProjectService(db).export_knowledge(project.id)

    assert "\nACTIVE_JOBS\n" in exported.content
    assert "  ACTIVE_PAY\n\n" in exported.content
    assert exported.content.index("## Vị trí tuyển dụng") < exported.content.index(
        "## Lương & thu nhập"
    )
    assert "UNPUBLISHED" not in exported.content
    assert "LEGACY_" not in exported.content
    assert "NEVER_EXPORT" not in exported.content


@pytest.mark.parametrize("mode", ["direct", "category", "legacy"])
async def test_export_hides_retired_references_without_rewriting_historical_source(integration_session, mode):
    db = integration_session
    project, base = await _project(
        db, mode=KnowledgeBaseMode.DIRECT_CONTEXT if mode == "direct" else KnowledgeBaseMode.RAG,
        authority=mode == "category",
    )
    source = (
        'Lương & thu nhập\njob_ids: ["old-role"]\njobs_ids:\n  - old-role\n'
        'vacancies: null\nemployment_type: temporary\nLương: 6 triệu\n'
    )
    if mode == "direct":
        row = await _direct(db, base, source)
        source_field = "raw_text"
    elif mode == "category":
        _category_row, row, _doc = await _category(db, project, "compensation", source)
        source_field = "source_markdown"
    else:
        version = await _version(db, project)
        row, _doc = await _legacy(db, project, version, source)
        source_field = "normalized_text"
    saved_sha = row.content_sha256

    exported = await ProjectService(db).export_knowledge(project.id)

    assert "job_ids" not in exported.content and "jobs_ids" not in exported.content
    assert "vacancies" not in exported.content and "employment_type" not in exported.content
    assert "old-role" not in exported.content
    assert "Lương: 6 triệu" in exported.content
    await db.refresh(row)
    assert getattr(row, source_field) == source
    assert row.content_sha256 == saved_sha


@pytest.mark.parametrize("mode", ["direct", "category", "legacy"])
async def test_export_rejects_source_with_only_retired_reference_fields(integration_session, mode):
    db = integration_session
    project, base = await _project(
        db, mode=KnowledgeBaseMode.DIRECT_CONTEXT if mode == "direct" else KnowledgeBaseMode.RAG,
        authority=mode == "category",
    )
    source = 'job_ids: ["old-role"]\njobs_ids: []\nvacancies: null\nemployment_type: null\n'
    if mode == "direct":
        await _direct(db, base, source)
    elif mode == "category":
        await _category(db, project, "compensation", source)
    else:
        version = await _version(db, project)
        await _legacy(db, project, version, source)

    with pytest.raises(ConflictError, match="chưa có kiến thức"):
        await ProjectService(db).export_knowledge(project.id)


@pytest.mark.parametrize(
    "status",
    [
        KnowledgeCategoryRevisionStatus.STAGED,
        KnowledgeCategoryRevisionStatus.PROCESSING,
        KnowledgeCategoryRevisionStatus.ARCHIVED,
        KnowledgeCategoryRevisionStatus.FAILED,
        KnowledgeCategoryRevisionStatus.CLEARED,
    ],
)
async def test_category_export_rejects_non_active_revision_even_when_pointer_is_present(
    integration_session,
    status,
):
    project, _base = await _project(integration_session)
    await _category(integration_session, project, "jobs", "NOT_CURRENT", status=status)

    with pytest.raises(ConflictError, match="chưa có kiến thức"):
        await ProjectService(integration_session).export_knowledge(project.id)


@pytest.mark.parametrize("mode", ["category", "legacy"])
@pytest.mark.parametrize(
    "status",
    [
        KnowledgeStatus.UPLOADED,
        KnowledgeStatus.PROCESSING,
        KnowledgeStatus.ARCHIVED,
        KnowledgeStatus.FAILED,
    ],
)
async def test_export_rejects_unpublished_or_retired_backing_document(
    integration_session, mode, status
):
    db = integration_session
    project, _base = await _project(db, authority=mode == "category")
    if mode == "category":
        await _category(db, project, "jobs", "REJECTED", document_status=status)
    else:
        version = await _version(db, project)
        await _legacy(db, project, version, "REJECTED", status=status)

    with pytest.raises(ConflictError, match="chưa có kiến thức"):
        await ProjectService(db).export_knowledge(project.id)


async def test_legacy_export_excludes_draft_version_pending_category_and_unlinked_source(
    integration_session,
):
    db = integration_session
    project, _base = await _project(db, authority=False)
    active = await _version(db, project)
    source = "  LEGACY_PUBLISHED_SAVED_SOURCE\n\n"
    await _legacy(db, project, active, source)
    await _legacy(db, project, active, "UNLINKED_SOURCE", linked=False)
    draft = await _version(db, project, number=2, status=KBVersionStatus.DRAFT, pointed=False)
    await _legacy(db, project, draft, "DRAFT_VERSION")
    await _category(db, project, "jobs", "CATEGORY_PENDING_CUTOVER")

    exported = await ProjectService(db).export_knowledge(project.id)

    assert source in exported.content
    for excluded in (
        "UNLINKED_SOURCE",
        "DRAFT_VERSION",
        "CATEGORY_PENDING",
        "OLD_UNREPAIRED",
        "NEVER_EXPORT",
    ):
        assert excluded not in exported.content


@pytest.mark.parametrize(
    "status", [item for item in KBVersionStatus if item != KBVersionStatus.ACTIVE]
)
async def test_legacy_export_requires_active_version_not_just_project_pointer(
    integration_session, status
):
    db = integration_session
    project, _base = await _project(db, authority=False)
    version = await _version(db, project, status=status)
    await _legacy(db, project, version, "NOT_PUBLISHED_VERSION")

    with pytest.raises(ConflictError):
        await ProjectService(db).export_knowledge(project.id)


@pytest.mark.parametrize(
    "broken_scope",
    [
        "category_document",
        "category_revision",
        "legacy_document",
        "legacy_file",
        "legacy_version",
        "base",
    ],
)
async def test_export_excludes_sources_owned_by_another_project(integration_session, broken_scope):
    db = integration_session
    project, base = await _project(db, authority=broken_scope.startswith("category"))
    other, other_base = await _project(db)
    if broken_scope == "category_document":
        await _category(db, project, "jobs", "OTHER_OWNER", document_owner=other.id)
    elif broken_scope == "category_revision":
        cat, _rev, _doc = await _category(db, project, "jobs", "LOCAL_UNUSED", pointed=False)
        _other_cat, other_rev, _other_doc = await _category(db, other, "jobs", "OTHER_OWNER")
        cat.active_revision_id = other_rev.id
    else:
        version = await _version(db, other if broken_scope == "legacy_version" else project)
        project.active_kb_version_id = version.id
        await _legacy(
            db,
            project,
            version,
            "OTHER_OWNER",
            document_owner=other.id if broken_scope == "legacy_document" else None,
            file_owner=other.id if broken_scope == "legacy_file" else None,
        )
        if broken_scope == "base":
            project.knowledge_base_id = None
            other.knowledge_base_id = None
            await db.flush()
            other.knowledge_base_id = base.id
            project.knowledge_base_id = other_base.id
    await db.flush()

    with pytest.raises(ConflictError):
        await ProjectService(db).export_knowledge(project.id)


@pytest.mark.parametrize("mode", ["direct", "category", "legacy"])
async def test_legacy_null_reverse_kb_owner_still_exports_declared_project_source(
    integration_session, mode
):
    db = integration_session
    project, base = await _project(
        db,
        authority=mode == "category",
        reverse_owner=False,
        mode=KnowledgeBaseMode.DIRECT_CONTEXT if mode == "direct" else KnowledgeBaseMode.RAG,
    )
    if mode == "direct":
        await _direct(db, base, "OWNED_LEGACY_SOURCE")
    elif mode == "category":
        await _category(db, project, "jobs", "OWNED_LEGACY_SOURCE")
    else:
        version = await _version(db, project)
        await _legacy(db, project, version, "OWNED_LEGACY_SOURCE")

    exported = await ProjectService(db).export_knowledge(project.id)

    assert "OWNED_LEGACY_SOURCE" in exported.content


@pytest.mark.parametrize("mode", ["direct", "category", "legacy"])
async def test_explicit_foreign_reverse_kb_owner_cannot_export(integration_session, mode):
    db = integration_session
    project, base = await _project(
        db,
        authority=mode == "category",
        mode=KnowledgeBaseMode.DIRECT_CONTEXT if mode == "direct" else KnowledgeBaseMode.RAG,
    )
    other = Project(slug=uuid.uuid4().hex, name="Other project")
    db.add(other)
    await db.flush()
    base.project_id = other.id
    if mode == "direct":
        await _direct(db, base, "FOREIGN_SOURCE")
    elif mode == "category":
        await _category(db, project, "jobs", "FOREIGN_SOURCE")
    else:
        version = await _version(db, project)
        await _legacy(db, project, version, "FOREIGN_SOURCE")
    await db.flush()

    with pytest.raises(ConflictError):
        await ProjectService(db).export_knowledge(project.id)


@pytest.mark.parametrize("state", ["no_base", "direct_empty", "cleared_category", "no_sources"])
async def test_existing_project_without_exportable_current_source_is_explicit_conflict(
    integration_session, state
):
    db = integration_session
    project, base = await _project(
        db,
        mode=KnowledgeBaseMode.DIRECT_CONTEXT if state == "direct_empty" else KnowledgeBaseMode.RAG,
    )
    if state == "no_base":
        project.knowledge_base_id = None
    elif state == "direct_empty":
        await _direct(db, base, " \n\t")
    elif state == "cleared_category":
        await _category(
            db,
            project,
            "jobs",
            "CLEARED_SOURCE",
            pointed=False,
            status=KnowledgeCategoryRevisionStatus.CLEARED,
        )
    await db.flush()

    with pytest.raises(ConflictError, match="chưa có kiến thức"):
        await ProjectService(db).export_knowledge(project.id)


async def test_unknown_project_is_not_found(integration_session):
    with pytest.raises(NotFoundError):
        await ProjectService(integration_session).export_knowledge(uuid.uuid4())


@pytest.mark.parametrize(
    "publication", ["category_cutover", "legacy_publication", "direct_cutover"]
)
async def test_export_uses_one_statement_snapshot_and_ignores_cached_authority(
    integration_database,
    publication,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id = None
    try:
        async with sessions() as setup:
            project, base = await _project(
                setup,
                authority=False,
                mode=KnowledgeBaseMode.DIRECT_CONTEXT
                if publication == "direct_cutover"
                else KnowledgeBaseMode.RAG,
            )
            project_id = project.id
            version = await _version(setup, project)
            if publication == "direct_cutover":
                await _direct(setup, base, "BEFORE_CUTOVER\n")
            else:
                await _legacy(setup, project, version, "BEFORE_CUTOVER\n")
            if publication == "legacy_publication":
                next_version = await _version(
                    setup, project, number=2, pointed=False, status=KBVersionStatus.READY
                )
                await _legacy(setup, project, next_version, "AFTER_CUTOVER\n")
            else:
                await _category(setup, project, "jobs", "AFTER_CUTOVER\n")
            await setup.commit()
        async with sessions() as reader, sessions() as writer:
            cached = await reader.get(Project, project_id)
            current = await writer.get(Project, project_id)
            if publication == "legacy_publication":
                old_version = await writer.get(KBVersion, version.id)
                new_version = await writer.get(KBVersion, next_version.id)
                old_version.status = KBVersionStatus.ARCHIVED
                # The real publisher archives before activating to respect
                # the one-ACTIVE-version index, inside the same transaction.
                await writer.flush()
                new_version.status = KBVersionStatus.ACTIVE
                current.active_kb_version_id = new_version.id
            else:
                current.category_authority_started = True
                if publication == "direct_cutover":
                    current_base = await writer.get(KnowledgeBase, base.id)
                    current_base.mode = KnowledgeBaseMode.RAG
            await writer.flush()
            statements = []

            def record_statement(_connection, _cursor, statement, _params, _context, _many):
                statements.append(statement)

            event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
            try:
                before = await ProjectService(reader).export_knowledge(project_id)
                assert len(statements) == 1
                assert statements[0].lstrip().startswith("SELECT")
                assert "BEFORE_CUTOVER\n" in before.content
                assert "AFTER_CUTOVER" not in before.content
                await writer.commit()
                statements.clear()
                after = await ProjectService(reader).export_knowledge(project_id)
                assert len(statements) == 1
                assert "AFTER_CUTOVER\n" in after.content
                assert "BEFORE_CUTOVER" not in after.content
                # A scalar snapshot must not read the stale identity-map flag.
                assert cached.category_authority_started is False
                assert cached.active_kb_version_id == version.id
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", record_statement)
    finally:
        if project_id:
            async with sessions() as cleanup:
                project = await cleanup.get(Project, project_id)
                project.knowledge_base_id = None
                project.active_kb_version_id = None
                await cleanup.flush()
                await cleanup.execute(delete(Project).where(Project.id == project_id))
                await cleanup.commit()
        await engine.dispose()
