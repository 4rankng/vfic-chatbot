"""Disposable PostgreSQL proof that one retained file trains the whole project."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.company import Project
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
    KBVersion,
    KBVersionStatus,
)
from app.models.user import Role, User
from app.project_knowledge.infrastructure.ingestion import SqlAlchemyKnowledgeIngestionAdapter
from app.schemas.knowledge import ProjectTrainingPlan
from app.schemas.projects import ProjectUpdate
from app.services.knowledge.category_markdown import build_source_markdown
from app.services.knowledge.project_training import ProjectTrainingService
from app.services.knowledge.category_service import KnowledgeCategoryService
from app.services.knowledge.category_service import CategoryActivationError
from app.services.knowledge.project_index_repository import ProjectIndexRepo
from app.services.knowledge.job_feature_repository import JobFeatureValueRepo
from app.services.retrieval.catalog_repository import CatalogRepository
from app.services.retrieval.document_repository import DocumentRepository
from app.models.job import Job
from app.models.company import Company
from app.services.knowledge.service import KnowledgeService
from app.services.knowledge.training_guard import ensure_training_owner
from app.services.knowledge.training_features import snapshot_feature_values
from app.services.project import ProjectService
from app.shared.domain.errors import ConflictError
from app.schemas.knowledge import KnowledgeDocumentOut

pytestmark = pytest.mark.integration


@pytest.fixture
async def atomic_session(integration_session):
    # Rollbacks in the production worker must preserve earlier committed setup.
    # Use savepoints inside the fixture's outer transaction for that proof.
    async with AsyncSession(
        bind=integration_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as db:
        yield db


_SOURCE = """Tên dự án: Xưởng điện tử Hải Phòng
Vị trí tuyển dụng: Công nhân, tại Hải Phòng.
Lương cơ bản 6.000.000 đồng mỗi tháng.
Yêu cầu: từ 18 tuổi, tốt nghiệp THPT.
Lịch làm việc: giờ hành chính.
Phúc lợi: đào tạo miễn phí.
Chỗ ở: không có ký túc xá.
Bữa ăn: có bữa trưa miễn phí.
Xe đưa đón: tuyến Hải Phòng hai chiều.
Bảo hiểm: BHXH theo quy định.
Ứng tuyển: gửi họ tên, số điện thoại, nguyện vọng.
Liên hệ: Bộ phận tuyển dụng, số 0901234567.
Câu hỏi: Có cần kinh nghiệm không? Trả lời: Được đào tạo từ đầu.
"""


def _plan():
    records = {
        "jobs": [{"id": "operator", "title": "Công nhân", "location": "Hải Phòng"}],
        "compensation": [{"id": "pay", "base_salary_vnd": 6_000_000}],
        "requirements": [
            {"id": "eligibility", "age_min": 18, "education": "THPT"}
        ],
        "work_schedules": [{"id": "schedule", "notes": "Giờ hành chính"}],
        "benefits": [{"id": "training", "name": "Đào tạo miễn phí"}],
        "accommodation": [{"id": "housing", "available": False, "notes": "Không có ký túc xá"}],
        "meals": [{"id": "meal", "provided": True, "notes": "Bữa trưa miễn phí"}],
        "transportation": [{"id": "bus", "name": "Tuyến Hải Phòng", "direction": "round_trip"}],
        "insurance": [{"id": "insurance", "name": "BHXH", "notes": "Theo quy định"}],
        "application": [
            {"id": "apply", "application_steps": ["Gửi họ tên, số điện thoại, nguyện vọng"]}
        ],
        "contacts": [{"id": "contact", "name": "Bộ phận tuyển dụng", "phone": "0901234567"}],
        "faq": [
            {
                "id": "experience",
                "question": "Có cần kinh nghiệm không?",
                "answer": "Được đào tạo từ đầu.",
            }
        ],
    }
    return ProjectTrainingPlan(
        writes=[
            {
                "key": key,
                "filename": f"{key}.md",
                "content": build_source_markdown(
                    {"schema_version": "1.0", "category": key, key: value}
                ),
            }
            for key, value in reversed(records.items())
        ]
    )


class _Embedder:
    async def __call__(self, _text):
        return [0.01] * 3072

    async def batch(self, texts):
        return [[0.01] * 3072 for _text in texts]


async def _upload(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.service.persist_original_upload", lambda *_args: None
    )
    actor = User(
        email=f"training-{uuid.uuid4().hex}@example.test", password_hash="not-used", role=Role.admin
    )
    project = Project(
        name="Xưởng điện tử Hải Phòng",
        slug=f"training-{uuid.uuid4().hex}",
        category_authority_started=True,
        is_active=False,
    )
    db.add_all([actor, project])
    await db.flush()
    base = KnowledgeBase(
        name=project.name,
        slug=project.slug,
        project_id=project.id,
        mode=KnowledgeBaseMode.RAG,
        created_by=actor.id,
    )
    db.add(base)
    await db.flush()
    project.knowledge_base_id = base.id
    await db.commit()
    doc = await KnowledgeService(db).upload_bytes(
        "brief.txt",
        "text/plain",
        _SOURCE.encode(),
        project_id=project.id,
        training_plan=_plan(),
        actor=actor,
    )
    return actor, project, doc


async def _train(db, doc, *, embedder=None):
    async def llm(system, _user):
        if "feature_key" in system:
            return json.dumps(
                {
                    "features": [
                        {
                            "feature_key": "take_home_income",
                            "value_text": "Lương cơ bản 6.000.000 đồng/tháng",
                            "evidence_text": "Lương cơ bản 6.000.000 đồng mỗi tháng.",
                            "is_missing": False,
                            "is_highlight": True,
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "document_summary": "Tuyển công nhân Hải Phòng",
                "units": [
                    {
                        "content": doc.raw_text,
                        "source_quote": doc.raw_text,
                        "category": "job",
                        "confidence": "high",
                        "is_inference": False,
                    }
                ],
            }
        )

    adapter = SqlAlchemyKnowledgeIngestionAdapter(db, providers=SimpleNamespace())
    await adapter.ingest_document(doc.id, embedder=embedder or _Embedder(), json_extractor=llm)


async def _pointers(db, project_id):
    return dict(
        (
            await db.execute(
                select(KnowledgeCategory.category_key, KnowledgeCategory.active_revision_id).where(
                    KnowledgeCategory.project_id == project_id
                )
            )
        ).all()
    )


async def _legacy_training(db, monkeypatch, *, existing_feature=True):
    actor, project, source = await _upload(db, monkeypatch)
    project.category_authority_started = False
    project.is_active = True
    project.summary = "Legacy factory summary"
    project.index_card = {
        "roles": ["Legacy operator"],
        "location": "Legacy location",
        "summary": project.summary,
        "highlights": ["Legacy salary"],
    }
    if existing_feature:
        income = await db.scalar(
            select(WorkerFeatureCatalog).where(
                WorkerFeatureCatalog.feature_key == "take_home_income"
            )
        )
        db.add(
            JobFeatureValue(
                project_id=project.id,
                feature_id=income.id,
                value_text="Legacy salary 3.000.000 đồng",
                value_json={"min": 3_000_000, "max": 3_000_000},
                is_highlight=True,
                evidence_text="Legacy salary",
            )
        )
    version = KBVersion(
        project_id=project.id, version_no=1, status=KBVersionStatus.ACTIVE, created_by=actor.id
    )
    legacy = KnowledgeDocument(
        project_id=project.id, file_name="legacy.md", source="legacy", status=KnowledgeStatus.PUBLISHED
    )
    db.add_all([version, legacy])
    await db.flush()
    project.active_kb_version_id = version.id
    await db.execute(
        text(
            "INSERT INTO knowledge_chunks (document_id, kb_version_id, chunk_index, "
            "chunk_type, content, content_plain, token_count, embedding, metadata, project_id) "
            "VALUES (:document_id, :version_id, 0, 'text', :content, :content, 3, "
            "CAST(:vector AS vector), '{}'::jsonb, :project_id)"
        ),
        {
            "document_id": legacy.id,
            "version_id": version.id,
            "content": "Legacy salary 3.000.000 đồng",
            "vector": "[" + ",".join(["0.01"] * 3072) + "]",
            "project_id": project.id,
        },
    )
    await db.commit()
    return actor, project, source


async def _visible_knowledge(db, project_id):
    rows = await DocumentRepository(db)._match_document_vector_rows(
        emb="[" + ",".join(["0.01"] * 3072) + "]",
        top_k=25,
        filter_json="{}",
        project_clause="AND d.project_id = ANY(CAST(:pids AS uuid[]))",
        project_ids=[str(project_id)],
    )
    return {row.content for row in rows}


@pytest.mark.parametrize("existing_feature", [True, False])
async def test_legacy_brief_features_publish_only_at_cutover_and_rollback_exactly(
    integration_session, monkeypatch, existing_feature
):
    db = integration_session
    actor, project, source = await _legacy_training(
        db, monkeypatch, existing_feature=existing_feature
    )
    previous = await snapshot_feature_values(db, project.id)
    previous_card = dict(project.index_card)
    await _train(db, source)
    await db.refresh(project)
    assert project.category_authority_started is False
    assert project.index_card == previous_card
    assert await snapshot_feature_values(db, project.id) == previous
    assert await _visible_knowledge(db, project.id) == {"Legacy salary 3.000.000 đồng"}
    payload = KnowledgeDocumentOut.model_validate(source).model_dump(mode="json")
    assert payload["project_training"]["status"] == "COMPLETED"
    assert payload["project_training"]["requires_cutover"] is True
    assert source.digest_meta["features"]["status"] == "DEFERRED_UNTIL_CUTOVER"
    catalog = CatalogRepository(db, page_project_ids=None)
    features = await catalog.job_features_for_project(project.id)
    assert [row.value_text for row in features] == (
        ["Legacy salary 3.000.000 đồng"] if existing_feature else []
    )
    before = next(
        row for row in await catalog.list_active_projects() if row.project_id == str(project.id)
    )
    assert before.salary_min == (3_000_000 if existing_feature else None)
    service = KnowledgeCategoryService(db)
    await service.cutover_category_authority(project_id=project.id, actor=actor)
    await db.refresh(project)
    await db.refresh(source)
    assert project.category_authority_started is True
    assert source.digest_meta["project_training"]["requires_cutover"] is False
    assert source.digest_meta["features"]["status"] == "COMPLETED"
    assert "Lương cơ bản 6.000.000 đồng/tháng" in project.index_card["highlights"]
    assert "Legacy salary 3.000.000 đồng" not in await _visible_knowledge(db, project.id)
    assert any(
        row.value_text == "Lương cơ bản 6.000.000 đồng/tháng"
        for row in await catalog.job_features_for_project(project.id)
    )
    assert project.category_cutover_snapshot["feature_values"] == previous
    await service.rollback_category_authority(project_id=project.id, actor=actor)
    await db.refresh(project)
    await db.refresh(source)
    assert project.category_authority_started is False
    assert project.index_card == previous_card
    assert await snapshot_feature_values(db, project.id) == previous
    assert await _visible_knowledge(db, project.id) == {"Legacy salary 3.000.000 đồng"}
    assert source.digest_meta["project_training"]["requires_cutover"] is True
    assert source.digest_meta["features"]["status"] == "DEFERRED_UNTIL_CUTOVER"


@pytest.mark.parametrize(
    "supersession", ["manual_category", "newer_source", "newer_failed_source", "manual_feature"]
)
async def test_legacy_cutover_never_adopts_superseded_source_features(
    integration_session, monkeypatch, supersession
):
    db = integration_session
    actor, project, source = await _legacy_training(db, monkeypatch)
    await _train(db, source)
    service = KnowledgeCategoryService(db)
    newer = None
    if supersession == "manual_category":
        write = next(write for write in _plan().writes if write.key.value == "contacts")
        await service.stage_replacement(
            project_id=project.id,
            category_key=write.key,
            filename=write.filename,
            source_markdown=write.content.replace("Bộ phận tuyển dụng", "Nhóm tuyển dụng mới"),
            actor=actor,
            schedule=False,
        )
    elif supersession in {"newer_source", "newer_failed_source"}:
        newer = await KnowledgeService(db).upload_bytes(
            "newer.txt", "text/plain", (_SOURCE + "\nNewer intent.\n").encode(),
            project_id=project.id, training_plan=_plan(), actor=actor,
        )
        if supersession == "newer_failed_source":
            newer.status = KnowledgeStatus.FAILED
            newer.digest_meta = {"project_training": {"status": "FAILED"}}
            await db.commit()
    else:
        feature = await db.scalar(
            select(JobFeatureValue).where(JobFeatureValue.project_id == project.id)
        )
        feature.value_text = "Independent edited salary 4.000.000 đồng"
        await db.commit()
    previous = await snapshot_feature_values(db, project.id)
    await service.cutover_category_authority(project_id=project.id, actor=actor)
    await db.refresh(project)
    await db.refresh(source)
    assert await snapshot_feature_values(db, project.id) == previous
    assert "feature_values" not in project.category_cutover_snapshot
    assert "deferred_feature_document_id" not in project.category_cutover_snapshot
    assert source.digest_meta["features"]["status"] == "SUPERSEDED"
    assert source.digest_meta["project_training"]["requires_cutover"] is False
    if newer is not None:
        await db.refresh(newer)
        assert newer.digest_meta["project_training"]["status"] == (
            "FAILED" if supersession == "newer_failed_source" else "QUEUED"
        )
    await service.rollback_category_authority(project_id=project.id, actor=actor)
    assert await snapshot_feature_values(db, project.id) == previous
    await db.refresh(source)
    assert source.digest_meta["project_training"]["requires_cutover"] is False


@pytest.mark.parametrize("existing_feature", [True, False])
async def test_passive_feature_get_keeps_shadow_intent_and_exact_rollback_snapshot(
    integration_session, monkeypatch, existing_feature
):
    db = integration_session
    actor, project, source = await _legacy_training(
        db, monkeypatch, existing_feature=existing_feature
    )
    await _train(db, source)
    await ProjectService(db).list_features(project.id)
    actual_before_cutover = await snapshot_feature_values(db, project.id)
    assert len(actual_before_cutover) > len(source.metadata_["project_training"]["feature_baseline"])
    duplicate = await KnowledgeService(db).upload_bytes(
        "brief.txt", "text/plain", _SOURCE.encode(),
        project_id=project.id, training_plan=_plan(), actor=actor,
    )
    assert duplicate.id == source.id
    service = KnowledgeCategoryService(db)
    await service.cutover_category_authority(project_id=project.id, actor=actor)
    await db.refresh(source)
    await db.refresh(project)
    assert source.digest_meta["features"]["status"] == "COMPLETED"
    assert source.digest_meta["project_training"]["requires_cutover"] is False
    assert project.category_cutover_snapshot["feature_values"] == actual_before_cutover
    await service.rollback_category_authority(project_id=project.id, actor=actor)
    assert await snapshot_feature_values(db, project.id) == actual_before_cutover
    await db.refresh(source)
    assert source.digest_meta["project_training"]["requires_cutover"] is True


@pytest.mark.parametrize("independent_edit", ["value", "evidence", "clarification", "provenance"])
async def test_real_feature_intent_allows_identical_brief_to_start_a_fresh_source(
    integration_session, monkeypatch, independent_edit
):
    db = integration_session
    actor, project, source = await _legacy_training(
        db, monkeypatch, existing_feature=independent_edit == "value"
    )
    await _train(db, source)
    await ProjectService(db).list_features(project.id)
    feature = await db.scalar(
        select(JobFeatureValue)
        .join(WorkerFeatureCatalog, WorkerFeatureCatalog.id == JobFeatureValue.feature_id)
        .where(
            JobFeatureValue.project_id == project.id,
            WorkerFeatureCatalog.feature_key == "take_home_income",
        )
    )
    if independent_edit == "value":
        feature.value_text = "New independent salary 4.000.000 đồng"
    elif independent_edit == "evidence":
        feature.evidence_text = "Administrator checked the source; salary is unspecified."
    elif independent_edit == "clarification":
        feature.needs_clarification = True
    else:
        feature.source_document_id = source.id
    await db.commit()
    fresh = await KnowledgeService(db).upload_bytes(
        "brief.txt", "text/plain", _SOURCE.encode(),
        project_id=project.id, training_plan=_plan(), actor=actor,
    )
    assert fresh.id != source.id
    retry = await KnowledgeService(db).upload_bytes(
        "brief.txt", "text/plain", _SOURCE.encode(),
        project_id=project.id, training_plan=_plan(), actor=actor,
    )
    assert retry.id == fresh.id


async def test_superseded_feature_intent_never_deduplicates_an_explicit_same_file_reupload(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, source = await _legacy_training(db, monkeypatch)
    await _train(db, source)
    feature = await db.scalar(
        select(JobFeatureValue).where(JobFeatureValue.project_id == project.id)
    )
    feature.value_text = "Independent salary 4.000.000 đồng"
    await db.commit()
    await KnowledgeCategoryService(db).cutover_category_authority(project_id=project.id, actor=actor)
    await db.refresh(source)
    assert source.digest_meta["features"]["status"] == "SUPERSEDED"
    fresh = await KnowledgeService(db).upload_bytes(
        "brief.txt", "text/plain", _SOURCE.encode(),
        project_id=project.id, training_plan=_plan(), actor=actor,
    )
    assert fresh.id != source.id
    await _train(db, fresh)
    assert fresh.digest_meta["features"]["status"] == "COMPLETED"
    assert fresh.digest_meta["project_training"]["requires_cutover"] is False


async def test_legacy_cutover_feature_failure_rolls_back_the_whole_authority_change(
    atomic_session, monkeypatch
):
    db = atomic_session
    actor, project, source = await _legacy_training(db, monkeypatch)
    await _train(db, source)
    previous = await snapshot_feature_values(db, project.id)
    previous_card = dict(project.index_card)
    ids = actor.id, project.id, source.id
    from app.services.knowledge import category_authority

    original = category_authority.publish_training_features

    async def fail_after_feature_writes(db, doc):
        await original(db, doc)
        raise RuntimeError("simulated legacy feature cutover SQL failure")

    monkeypatch.setattr(category_authority, "publish_training_features", fail_after_feature_writes)
    with pytest.raises(RuntimeError, match="simulated legacy"):
        await KnowledgeCategoryService(db).cutover_category_authority(
            project_id=project.id, actor=actor
        )
    await db.rollback()
    project = await db.get(Project, ids[1])
    source = await db.get(KnowledgeDocument, ids[2])
    assert project.category_authority_started is False
    assert project.category_cutover_snapshot is None
    assert project.index_card == previous_card
    assert await snapshot_feature_values(db, project.id) == previous
    assert source.digest_meta["project_training"]["requires_cutover"] is True


async def test_live_third_category_attempt_survives_duplicate_delivery(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, _doc = await _upload(db, monkeypatch)
    service = KnowledgeCategoryService(db, enforce_retrieval_selftest=False)
    write = next(write for write in _plan().writes if write.key.value == "contacts")
    revision, _ = await service.stage_replacement(
        project_id=project.id,
        category_key=write.key,
        filename=write.filename,
        source_markdown=write.content,
        actor=actor,
        schedule=False,
    )
    token = uuid.uuid4()
    from datetime import UTC, datetime, timedelta

    revision.status = KnowledgeCategoryRevisionStatus.PROCESSING
    revision.attempt_count = 3
    revision.processing_token = token
    revision.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    await db.commit()

    await service.activate_revision(revision.id, _Embedder())
    await db.refresh(revision)
    assert revision.status is KnowledgeCategoryRevisionStatus.PROCESSING
    assert revision.processing_token == token
    assert revision.lease_expires_at is not None


async def test_returning_to_active_content_supersedes_a_pending_other_edit(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, _doc = await _upload(db, monkeypatch)
    service = KnowledgeCategoryService(db)
    a = next(write for write in _plan().writes if write.key.value == "jobs")

    async def stage(content):
        return (
            await service.stage_replacement(
                project_id=project.id,
                category_key=a.key,
                filename=a.filename,
                source_markdown=content,
                actor=actor,
                schedule=False,
            )
        )[0]

    first = await stage(a.content)
    await service.activate_revision(first.id, _Embedder())
    pending = await stage(a.content.replace("Công nhân", "Nhân viên mới"))
    returned = await stage(a.content)
    assert returned.id != first.id
    assert returned.revision_no > pending.revision_no
    await service.activate_revision(pending.id, _Embedder())
    await db.refresh(pending)
    assert pending.status is KnowledgeCategoryRevisionStatus.ARCHIVED
    await service.activate_revision(returned.id, _Embedder())
    assert (await _pointers(db, project.id))["jobs"] == returned.id


async def test_training_replaces_roles_without_rewriting_other_project_facts(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, doc = await _upload(db, monkeypatch)
    await _train(db, doc)
    project.is_active = True
    await db.commit()
    old = await _pointers(db, project.id)
    plan = _plan()
    for write in plan.writes:
        write.content = write.content.replace("operator", "operator-v2")
    replacement = await KnowledgeService(db).upload_bytes(
        "new-role.txt",
        "text/plain",
        (_SOURCE + "\nUpdated role.\n").encode(),
        project_id=project.id,
        training_plan=plan,
        actor=actor,
    )
    await _train(db, replacement)
    current = await _pointers(db, project.id)
    assert current["jobs"] != old["jobs"]
    assert current["compensation"] == old["compensation"]
    roles = await db.scalars(select(Job).join(Company).where(Company.project_id == project.id))
    assert any(role.stable_key == "operator-v2" and role.salary_min == 6_000_000 for role in roles)
    # The old derived Job can be retained for historical applications, but it
    # must not stay discoverable as a current recruitment role.
    results = await CatalogRepository(db, page_project_ids=None).list_active_projects()
    project_result = next(row for row in results if row.project_id == str(project.id))
    assert [item.title for item in project_result.scope] == ["Công nhân"]


async def test_failed_category_preparation_preserves_published_features_card_and_all_pointers(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, doc = await _upload(db, monkeypatch)
    await _train(db, doc)
    before = await _pointers(db, project.id)
    await db.refresh(project)
    card = dict(project.index_card)
    features = await JobFeatureValueRepo(db).list_for_project(project.id)
    feature_sources = {row.feature_key: row.source_document_id for row in features}
    replacement_plan = _plan()
    for write in replacement_plan.writes:
        write.filename = "new-" + write.filename
    replacement = await KnowledgeService(db).upload_bytes(
        "new.txt",
        "text/plain",
        (_SOURCE + "\nReplacement.\n").encode(),
        project_id=project.id,
        training_plan=replacement_plan,
        actor=actor,
    )

    class Failing(_Embedder):
        async def batch(self, texts):
            if any(text.startswith("Lương") for text in texts):
                raise RuntimeError("provider unavailable")
            return await super().batch(texts)

    with pytest.raises(CategoryActivationError):
        await _train(db, replacement, embedder=Failing())
    await db.refresh(project)
    await db.refresh(replacement)
    assert replacement.status is KnowledgeStatus.FAILED
    assert await _pointers(db, project.id) == before
    assert project.index_card == card
    after = await JobFeatureValueRepo(db).list_for_project(project.id)
    assert {row.feature_key: row.source_document_id for row in after} == feature_sources
    assert (await ProjectService(db).get_with_readiness(project.id)).ingest_state == "error"
    # A retry reuses prepared category documents and publishes only after the
    # remaining category succeeds; no intermediate source chunk becomes visible.
    prepared_count = await db.scalar(
        select(func.count())
        .select_from(KnowledgeDocument)
        .where(
            KnowledgeDocument.metadata_["project_training_document_id"].as_string()
            == str(replacement.id)
        )
    )
    assert prepared_count > 0
    duplicate = await KnowledgeService(db).upload_bytes(
        "same-new.txt",
        "text/plain",
        (_SOURCE + "\nReplacement.\n").encode(),
        project_id=project.id,
        training_plan=replacement_plan,
        actor=actor,
    )
    assert duplicate.id == replacement.id
    await _train(db, replacement)
    assert replacement.status is KnowledgeStatus.PUBLISHED
    assert (
        await db.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(
                KnowledgeDocument.metadata_["project_training_document_id"].as_string()
                == str(replacement.id)
            )
        )
        == 12
    )


async def test_failed_selftest_preparation_persists_the_offending_query(
    integration_session, monkeypatch
):
    """The batch failure path must keep the gate's detail, not a generic string.

    Production incident: the training batch overwrote the retrieval selftest's
    per-record diagnostics with "Category preparation failed", leaving only a
    bare "Cập nhật lỗi" card. The service path (activate_revision) already
    stores str(exc); the batch path must match.
    """

    async def failing_selftest(document, units, vectors, embedder):
        return [
            '"Có cần kinh nghiệm không?" would not retrieve its own record '
            "(own-record similarity 0.00 < 0.50)"
        ]

    monkeypatch.setattr(
        "app.services.knowledge.category_batch.retrieval_selftest_failures",
        failing_selftest,
    )
    db = integration_session
    actor, project, doc = await _upload(db, monkeypatch)
    with pytest.raises(CategoryActivationError):
        await _train(db, doc)
    revision = await db.scalar(
        select(KnowledgeCategoryRevision).where(
            KnowledgeCategoryRevision.status == KnowledgeCategoryRevisionStatus.FAILED
        )
    )
    assert revision is not None
    assert revision.failure_code == "category_retrieval_selftest_failed"
    assert "Có cần kinh nghiệm không?" in (revision.error_message or "")
    assert revision.error_message != "Category preparation failed"


async def test_cutover_sql_failure_rolls_back_features_pointers_and_projections(
    atomic_session, monkeypatch
):
    db = atomic_session
    actor, project, doc = await _upload(db, monkeypatch)
    await _train(db, doc)
    before = await _pointers(db, project.id)
    await db.refresh(project)
    card = dict(project.index_card)
    sources = {
        row.feature_key: row.source_document_id
        for row in await JobFeatureValueRepo(db).list_for_project(project.id)
    }
    plan = _plan()
    for write in plan.writes:
        write.filename = "replacement-" + write.filename
    replacement = await KnowledgeService(db).upload_bytes(
        "replacement.txt",
        "text/plain",
        (_SOURCE + "\nChanged.\n").encode(),
        project_id=project.id,
        training_plan=plan,
        actor=actor,
    )
    original = ProjectIndexRepo.sync_highlights

    async def fail_after_writes(self, project_id, *, commit=True):
        await original(self, project_id, commit=commit)
        if not commit:
            raise RuntimeError("simulated cutover failure after feature SQL")

    monkeypatch.setattr(ProjectIndexRepo, "sync_highlights", fail_after_writes)
    with pytest.raises(RuntimeError, match="simulated cutover"):
        await _train(db, replacement)
    await db.refresh(project)
    assert await _pointers(db, project.id) == before
    assert project.index_card == card
    assert {
        row.feature_key: row.source_document_id
        for row in await JobFeatureValueRepo(db).list_for_project(project.id)
    } == sources


async def test_same_completed_file_is_new_intent_after_a_manual_pending_edit(
    atomic_session, monkeypatch
):
    db = atomic_session
    actor, project, doc = await _upload(db, monkeypatch)
    await _train(db, doc)
    write = next(write for write in _plan().writes if write.key.value == "jobs")
    manual, _ = await KnowledgeCategoryService(db).stage_replacement(
        project_id=project.id,
        category_key=write.key,
        filename="manual.md",
        source_markdown=write.content.replace("Công nhân", "Nội dung thủ công"),
        actor=actor,
        schedule=False,
    )
    recovered = await KnowledgeService(db).upload_bytes(
        "brief.txt",
        "text/plain",
        _SOURCE.encode(),
        project_id=project.id,
        training_plan=_plan(),
        actor=actor,
    )
    assert recovered.id != doc.id
    await _train(db, recovered)
    assert (await _pointers(db, project.id))["jobs"] != manual.id


async def test_explicit_reprocess_of_current_completed_source_keeps_a_valid_published_snapshot(
    atomic_session, monkeypatch
):
    db = atomic_session
    actor, project, doc = await _upload(db, monkeypatch)
    await _train(db, doc)
    pointers = await _pointers(db, project.id)
    await KnowledgeService(db).queue_document(
        doc, jobs=SimpleNamespace(ingest_document=lambda _id: None)
    )
    assert doc.digest_meta["project_training"]["status"] == "QUEUED"
    await _train(db, doc)
    assert doc.status is KnowledgeStatus.PUBLISHED
    assert doc.digest_meta["project_training"]["status"] == "COMPLETED"
    assert await _pointers(db, project.id) == pointers


@pytest.mark.parametrize("interruption", ["manual_edit", "newer_source", "reclaimed_source"])
async def test_batch_cannot_publish_after_concurrent_knowledge_or_claim_change(
    atomic_session, monkeypatch, interruption
):
    db = atomic_session
    actor, project, doc = await _upload(db, monkeypatch)
    await _train(db, doc)
    before = await _pointers(db, project.id)
    plan = _plan()
    for write in plan.writes:
        write.filename = "new-" + write.filename
    replacement = await KnowledgeService(db).upload_bytes(
        "replacement.txt",
        "text/plain",
        (_SOURCE + "\nChanged.\n").encode(),
        project_id=project.id,
        training_plan=plan,
        actor=actor,
    )
    interrupted = False

    class Interleaved(_Embedder):
        async def batch(self, texts):
            nonlocal interrupted
            if not interrupted and any(text.startswith("Vị trí") for text in texts):
                interrupted = True
                if interruption == "manual_edit":
                    write = next(write for write in _plan().writes if write.key.value == "jobs")
                    await KnowledgeCategoryService(db).stage_replacement(
                        project_id=project.id,
                        category_key=write.key,
                        filename="manual.md",
                        source_markdown=write.content.replace("Công nhân", "Lắp ráp mới"),
                        actor=actor,
                        schedule=False,
                    )
                elif interruption == "newer_source":
                    await KnowledgeService(db).upload_bytes(
                        "later.txt",
                        "text/plain",
                        (_SOURCE + "\nLater source.\n").encode(),
                        project_id=project.id,
                        training_plan=_plan(),
                        actor=actor,
                    )
                else:
                    replacement.metadata_ = {
                        **replacement.metadata_,
                        "project_training": {
                            **replacement.metadata_["project_training"],
                            "processing_token": str(uuid.uuid4()),
                        },
                    }
                    await db.commit()
            return await super().batch(texts)

    with pytest.raises(CategoryActivationError):
        await _train(db, replacement, embedder=Interleaved())
    assert interrupted
    await db.refresh(project)
    assert await _pointers(db, project.id) == before
    if interruption == "manual_edit":
        # An explicit identical reupload is now a new intent; reusing this
        # invalidated snapshot would make recovery impossible forever.
        await db.refresh(actor)
        recovered = await KnowledgeService(db).upload_bytes(
            "replacement.txt",
            "text/plain",
            (_SOURCE + "\nChanged.\n").encode(),
            project_id=project.id,
            training_plan=plan,
            actor=actor,
        )
        assert recovered.id != replacement.id
        await _train(db, recovered)
        assert recovered.status is KnowledgeStatus.PUBLISHED


async def test_matching_manual_retry_of_source_owned_revision_is_an_explicit_conflict(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, doc = await _upload(db, monkeypatch)
    service = ProjectTrainingService(db)
    assert await service.claim(doc)
    plan = _plan()
    await service.batch.stage(doc, plan, actor)
    write = plan.writes[0]
    with pytest.raises(ConflictError, match="thử xử lý lại tệp"):
        await KnowledgeCategoryService(db).stage_replacement(
            project_id=project.id,
            category_key=write.key,
            filename=write.filename,
            source_markdown=write.content,
            actor=actor,
            schedule=True,
        )


async def test_one_upload_trains_twelve_categories_features_and_reuses_exact_reupload(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, doc = await _upload(db, monkeypatch)
    retained_id = doc.id

    async def llm(system, _user):
        if "feature_key" in system:
            return json.dumps(
                {
                    "features": [
                        {
                            "feature_key": "take_home_income",
                            "value_text": "Lương cơ bản 6.000.000 đồng/tháng",
                            "evidence_text": "Lương cơ bản 6.000.000 đồng mỗi tháng.",
                            "is_missing": False,
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "document_summary": "Tuyển công nhân Hải Phòng",
                "units": [
                    {
                        "content": _SOURCE,
                        "source_quote": _SOURCE,
                        "category": "job",
                        "confidence": "high",
                        "is_inference": False,
                    }
                ],
            }
        )

    adapter = SqlAlchemyKnowledgeIngestionAdapter(db, providers=SimpleNamespace())
    await adapter.ingest_document(doc.id, embedder=_Embedder(), json_extractor=llm)
    await db.refresh(doc)
    assert doc.status is KnowledgeStatus.PUBLISHED
    assert doc.digest_meta["project_training"]["status"] == "COMPLETED"
    assert len(doc.digest_meta["project_training"]["completed"]) == 12
    assert doc.digest_meta["features"]["status"] == "COMPLETED"
    assert doc.raw_text == _SOURCE
    assert (
        await db.scalar(
            select(func.count())
            .select_from(KnowledgeCategory)
            .where(
                KnowledgeCategory.project_id == project.id,
                KnowledgeCategory.active_revision_id.is_not(None),
            )
        )
        == 12
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(KnowledgeCategoryRevision)
            .where(
                KnowledgeCategoryRevision.status == KnowledgeCategoryRevisionStatus.ACTIVE,
                KnowledgeCategoryRevision.category_id.in_(
                    select(KnowledgeCategory.id).where(KnowledgeCategory.project_id == project.id)
                ),
            )
        )
        == 12
    )

    # A second copy of the same source and plan resumes/reuses the receipt,
    # rather than creating a competing new source or twelve more revisions.
    duplicate = await KnowledgeService(db).upload_bytes(
        "same-brief.txt",
        "text/plain",
        _SOURCE.encode(),
        project_id=project.id,
        training_plan=_plan(),
        actor=actor,
    )
    assert duplicate.id == retained_id
    await adapter.ingest_document(doc.id, embedder=_Embedder(), json_extractor=llm)
    assert (
        await db.scalar(
            select(func.count())
            .select_from(KnowledgeCategoryRevision)
            .where(
                KnowledgeCategoryRevision.category_id.in_(
                    select(KnowledgeCategory.id).where(KnowledgeCategory.project_id == project.id)
                )
            )
        )
        == 12
    )
    await db.refresh(project)
    assert project.is_active is False  # Publication remains the admin's decision.
    activated = await ProjectService(db).update(project.id, ProjectUpdate(is_active=True), actor)
    assert activated.is_active is True

    # A replacement may continue training while the existing project recruits.
    replacement = await KnowledgeService(db).upload_bytes(
        "replacement.txt",
        "text/plain",
        (_SOURCE + "New note.").encode(),
        project_id=project.id,
        training_plan=_plan(),
        actor=actor,
    )
    replacement.status = KnowledgeStatus.FAILED
    replacement.digest_meta = {"project_training": {"status": "FAILED", "completed": []}}
    await db.commit()
    edited = await ProjectService(db).update(
        project.id, ProjectUpdate(name="Xưởng đang tuyển", is_active=True), actor
    )
    assert edited.is_active is True
    assert edited.name == "Xưởng đang tuyển"


async def test_draft_cannot_publish_until_latest_source_and_receipt_are_completed(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, doc = await _upload(db, monkeypatch)
    for document_status, receipt_status in [
        (KnowledgeStatus.UPLOADED, "QUEUED"),
        (KnowledgeStatus.PROCESSING, "PROCESSING"),
        (KnowledgeStatus.FAILED, "FAILED"),
        (KnowledgeStatus.PUBLISHED, "PROCESSING"),
        (KnowledgeStatus.PROCESSING, "COMPLETED"),
    ]:
        doc.status = document_status
        doc.digest_meta = {"project_training": {"status": receipt_status, "completed": []}}
        await db.commit()
        with pytest.raises(ConflictError, match="chưa được xử lý xong"):
            await ProjectService(db).update(project.id, ProjectUpdate(is_active=True), actor)
        # A policy conflict does not abort the SQL transaction. The fixture's
        # outer transaction retains setup rows until test teardown.
        await db.commit()
        await db.refresh(project)
        await db.refresh(doc)
        assert project.is_active is False


async def test_activation_holds_project_lock_until_commit_against_a_new_source(
    integration_database, monkeypatch
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    checked, release, upload_waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    publication = upload = None

    class UploadSession:
        def __init__(self, session):
            self.session = session

        def __getattr__(self, name):
            return getattr(self.session, name)

        async def scalar(self, statement):
            if (
                statement.column_descriptions[0]["entity"] is Project
                and statement._for_update_arg is not None
            ):
                upload_waiting.set()
            return await self.session.scalar(statement)

    try:
        # Independent sessions need committed setup, outside the standard
        # integration_session fixture's enclosing rollback transaction.
        async with sessions() as setup:
            actor, project, doc = await _upload(setup, monkeypatch)
            doc.status = KnowledgeStatus.PUBLISHED
            doc.digest_meta = {"project_training": {"status": "COMPLETED", "completed": []}}
            await setup.commit()
            actor_id, project_id = actor.id, project.id
        async with sessions() as publisher, sessions() as uploader:
            publisher_actor = await publisher.get(User, actor_id)
            uploader_actor = await uploader.get(User, actor_id)
            service = ProjectService(publisher)
            original_check = service._require_activation_ready

            async def pause_after_check(project):
                await original_check(project)
                checked.set()
                await release.wait()

            service._require_activation_ready = pause_after_check
            publication = asyncio.create_task(
                service.update(project_id, ProjectUpdate(is_active=True), publisher_actor)
            )
            await asyncio.wait_for(checked.wait(), timeout=5)
            upload = asyncio.create_task(
                KnowledgeService(UploadSession(uploader)).upload_bytes(
                    "new.txt",
                    "text/plain",
                    (_SOURCE + "New note.").encode(),
                    project_id=project_id,
                    training_plan=_plan(),
                    actor=uploader_actor,
                )
            )
            await asyncio.wait_for(upload_waiting.wait(), timeout=5)
            assert not upload.done()  # No source may commit after the check but before publication.
            release.set()
            activated, replacement = await asyncio.wait_for(
                asyncio.gather(publication, upload), timeout=5
            )
            assert activated.is_active is True
            assert replacement.digest_meta["project_training"]["status"] == "QUEUED"
    finally:
        release.set()
        for task in (publication, upload):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (publication, upload) if task is not None),
            return_exceptions=True,
        )
        await engine.dispose()


async def test_archived_newer_source_no_longer_supersedes_retained_source(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, first = await _upload(db, monkeypatch)
    claimant = ProjectTrainingService(db)
    assert await claimant.claim(first)
    second = await KnowledgeService(db).upload_bytes(
        "newer.txt",
        "text/plain",
        (_SOURCE + "New note.").encode(),
        project_id=project.id,
        training_plan=_plan(),
        actor=actor,
    )
    with pytest.raises(ConflictError, match="newer training source"):
        await ensure_training_owner(db, first.id, project.id, claimant.processing_token)
    await db.commit()
    await db.refresh(first)
    await db.refresh(second)
    await db.refresh(project)
    await db.refresh(actor)
    second.status = KnowledgeStatus.ARCHIVED
    await db.commit()

    retained = await KnowledgeService(db).upload_bytes(
        "retry.txt",
        "text/plain",
        _SOURCE.encode(),
        project_id=project.id,
        training_plan=_plan(),
        actor=actor,
    )
    assert retained.id == first.id
    await ensure_training_owner(db, first.id, project.id, claimant.processing_token)
    await db.commit()

    # Withdrawing the owner itself must still reject a late worker.
    first.status = KnowledgeStatus.ARCHIVED
    await db.commit()
    assert await ProjectTrainingService(db).claim(first) is False
    with pytest.raises(ConflictError, match="no longer owns"):
        await ensure_training_owner(db, first.id, project.id, claimant.processing_token)


async def test_new_claim_fences_old_training_checkpoint(integration_session, monkeypatch):
    db = integration_session
    _actor, project, doc = await _upload(db, monkeypatch)
    claimant = ProjectTrainingService(db)
    assert await claimant.claim(doc)
    previous_token = claimant.processing_token
    training = dict(doc.metadata_["project_training"])
    training["processing_token"] = str(uuid.uuid4())
    doc.metadata_ = {**doc.metadata_, "project_training": training}
    await db.commit()

    with pytest.raises(ConflictError, match="no longer owns"):
        await ensure_training_owner(db, doc.id, project.id, previous_token)


async def test_invalid_full_plan_does_not_retain_source_or_any_category(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, _doc = await _upload(db, monkeypatch)
    invalid = _plan()
    invalid.writes[-1].content = "invalid category markdown"
    before = await db.scalar(select(func.count()).select_from(KnowledgeDocument))

    with pytest.raises(ValueError):
        await KnowledgeService(db).upload_bytes(
            "invalid.txt",
            "text/plain",
            b"invalid new source",
            project_id=project.id,
            training_plan=invalid,
            actor=actor,
        )
    assert await db.scalar(select(func.count()).select_from(KnowledgeDocument)) == before


async def test_reverting_to_an_earlier_file_creates_a_new_latest_source(
    integration_session, monkeypatch
):
    db = integration_session
    actor, project, first = await _upload(db, monkeypatch)
    service = KnowledgeService(db)
    second = await service.upload_bytes(
        "new.txt",
        "text/plain",
        (_SOURCE + "Nouvelle note.").encode(),
        project_id=project.id,
        training_plan=_plan(),
        actor=actor,
    )
    reverted = await service.upload_bytes(
        "first.txt",
        "text/plain",
        _SOURCE.encode(),
        project_id=project.id,
        training_plan=_plan(),
        actor=actor,
    )
    assert reverted.id not in {first.id, second.id}
    assert reverted.created_at >= second.created_at


async def test_preloaded_duplicate_session_cannot_steal_live_training_claim(integration_database):
    """A row lock must refresh identity-map state loaded before another claim."""
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    document_id = uuid.uuid4()
    try:
        async with sessions() as owner:
            owner.add(
                KnowledgeDocument(
                    id=document_id,
                    file_name="race.txt",
                    source="upload",
                    status=KnowledgeStatus.UPLOADED,
                    stage="EXTRACTED",
                    raw_text=_SOURCE,
                    metadata_={"project_training": {}},
                    digest_meta={"project_training": {"status": "QUEUED", "completed": []}},
                )
            )
            await owner.commit()
        async with sessions() as first, sessions() as duplicate:
            first_doc = await first.get(KnowledgeDocument, document_id)
            duplicate_doc = await duplicate.get(KnowledgeDocument, document_id)
            assert await ProjectTrainingService(first).claim(first_doc)
            assert await ProjectTrainingService(duplicate).claim(duplicate_doc) is False
        async with sessions() as cleanup:
            await cleanup.execute(
                delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
            )
            await cleanup.commit()
    finally:
        await engine.dispose()


async def test_training_retained_old_plan_stores_project_categories_without_retired_fields(
    integration_session,
    monkeypatch,
):
    db = integration_session
    _actor, project, doc = await _upload(db, monkeypatch)
    training = dict(doc.metadata_["project_training"])
    writes = [dict(write) for write in training["writes"]]
    compensation = next(write for write in writes if write["key"] == "compensation")
    compensation["content"] = compensation["content"].replace(
        "### record: pay\n", "### record: pay\njob_ids:\n- old-role\njobs_ids: [older-role]\n"
    )
    doc.metadata_ = {**doc.metadata_, "project_training": {**training, "writes": writes}}
    await db.commit()
    await _train(db, doc)
    revisions = list(
        (
            await db.scalars(
                select(KnowledgeCategoryRevision)
                .join(
                    KnowledgeCategory, KnowledgeCategoryRevision.category_id == KnowledgeCategory.id
                )
                .where(
                    KnowledgeCategory.project_id == project.id,
                    KnowledgeCategory.category_key == "compensation",
                )
            )
        ).all()
    )
    assert len(revisions) == 1
    assert revisions[0].quality_result["schema_check"] == "passed"
    assert "reference_check" not in revisions[0].quality_result
    assert "job_ids" not in revisions[0].source_markdown
    assert "jobs_ids" not in revisions[0].source_markdown
    assert "job_ids" not in str(revisions[0].normalized_payload)
    jobs = list(
        (await db.scalars(select(Job).join(Company).where(Company.project_id == project.id))).all()
    )
    assert [job.salary_min for job in jobs] == [6_000_000]
