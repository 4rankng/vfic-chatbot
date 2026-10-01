"""Disposable PostgreSQL proof that one retained file trains the whole project."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.company import Project
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.models.user import Role, User
from app.project_knowledge.infrastructure.ingestion import SqlAlchemyKnowledgeIngestionAdapter
from app.schemas.knowledge import ProjectTrainingPlan
from app.schemas.projects import ProjectUpdate
from app.services.knowledge.category_markdown import build_source_markdown
from app.services.knowledge.project_training import ProjectTrainingService
from app.services.knowledge.service import KnowledgeService
from app.services.knowledge.training_guard import ensure_training_owner
from app.services.project import ProjectService
from app.shared.domain.errors import ConflictError

pytestmark = pytest.mark.integration

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
        "compensation": [{"id": "pay", "job_ids": ["operator"], "base_salary_vnd": 6_000_000}],
        "requirements": [
            {"id": "eligibility", "job_ids": ["operator"], "age_min": 18, "education": "THPT"}
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
        "replacement.txt", "text/plain", (_SOURCE + "New note.").encode(),
        project_id=project.id, training_plan=_plan(), actor=actor,
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
                    "new.txt", "text/plain", (_SOURCE + "New note.").encode(),
                    project_id=project_id, training_plan=_plan(), actor=uploader_actor,
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
        "newer.txt", "text/plain", (_SOURCE + "New note.").encode(),
        project_id=project.id, training_plan=_plan(), actor=actor,
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
        "retry.txt", "text/plain", _SOURCE.encode(),
        project_id=project.id, training_plan=_plan(), actor=actor,
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
            owner.add(KnowledgeDocument(
                id=document_id, file_name="race.txt", source="upload", status=KnowledgeStatus.UPLOADED,
                stage="EXTRACTED", raw_text=_SOURCE, metadata_={"project_training": {}},
                digest_meta={"project_training": {"status": "QUEUED", "completed": []}},
            ))
            await owner.commit()
        async with sessions() as first, sessions() as duplicate:
            first_doc = await first.get(KnowledgeDocument, document_id)
            duplicate_doc = await duplicate.get(KnowledgeDocument, document_id)
            assert await ProjectTrainingService(first).claim(first_doc)
            assert await ProjectTrainingService(duplicate).claim(duplicate_doc) is False
        async with sessions() as cleanup:
            await cleanup.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
            await cleanup.commit()
    finally:
        await engine.dispose()
