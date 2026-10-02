"""Automatic source publication must not overwrite intervening feature edits."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company, Project
from app.models.job import Job
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog
from app.schemas.projects import FeatureUpdate
from app.services.knowledge import category_batch
from app.services.knowledge.job_feature_repository import JobFeatureValueRepo
from app.services.knowledge.service import KnowledgeService
from app.services.knowledge.training_features import (
    auto_training_feature_intent_current,
    capture_auto_training_feature_baseline,
    publish_training_features,
    snapshot_feature_values,
)
from app.services.project.features import ProjectFeatureService
from app.shared.domain.errors import ConflictError
from tests.integration.test_project_training import _Embedder, _SOURCE, _pointers, _train, _upload

pytestmark = pytest.mark.integration


@pytest.fixture
async def feature_session(integration_session):
    async with AsyncSession(
        bind=integration_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as db:
        yield db


def _prepared_value(text, *, missing=False):
    return {
        "value_text": text,
        "value_json": {},
        "strength_score": "0.90",
        "is_highlight": not missing,
        "is_missing": missing,
        "needs_clarification": False,
        "evidence_text": text or "Chưa có thông tin trong nguồn đã tải lên.",
    }


async def _source(db, *, auto=True, existing=True):
    project = Project(
        name="Feature guard fixture",
        slug=f"auto-feature-guard-{uuid.uuid4().hex}",
        is_active=False,
        category_authority_started=True,
    )
    db.add(project)
    await db.flush()
    catalog = await db.scalar(
        select(WorkerFeatureCatalog).where(WorkerFeatureCatalog.feature_key == "take_home_income")
    )
    assert catalog is not None
    source = KnowledgeDocument(
        project_id=project.id,
        file_name="source.txt",
        source="upload",
        raw_text="Thu nhập 8 triệu đồng.",
        status=KnowledgeStatus.PROCESSING,
        metadata_={"project_training": {
            "auto_extract": auto,
            "feature_values": [{"feature_id": str(catalog.id), "value": _prepared_value("8 triệu đồng")}],
        }},
        digest_meta={"project_training": {"status": "PROCESSING"}},
    )
    db.add(source)
    await db.flush()
    feature = None
    if existing:
        feature = JobFeatureValue(
            project_id=project.id,
            feature_id=catalog.id,
            value_text="6 triệu đồng",
            value_json={},
            strength_score=Decimal("0.90"),
            display_priority=0,
            is_highlight=True,
            is_missing=False,
            needs_clarification=False,
            evidence_text="Thu nhập 6 triệu đồng.",
        )
        db.add(feature)
        await db.flush()
    if auto:
        source.metadata_ = {"project_training": {
            **source.metadata_["project_training"],
            "auto_feature_baseline": await capture_auto_training_feature_baseline(db, project.id),
        }}
    await db.commit()
    return project, source, catalog, feature


@pytest.mark.parametrize("edit", ["value_text", "is_highlight", "evidence_text"])
async def test_manual_feature_edit_blocks_auto_publication(feature_session, edit):
    db = feature_session
    _project, source, _catalog, feature = await _source(db)
    assert feature is not None
    changes = {"value_text": "7 triệu đồng", "is_highlight": False, "evidence_text": "Thông tin quản trị mới"}
    setattr(feature, edit, changes[edit])
    await db.commit()  # The edit lands while provider work is outside its transaction.
    assert not await auto_training_feature_intent_current(db, source)

    with pytest.raises(ConflictError, match="đã được chỉnh sửa"):
        await publish_training_features(db, source)
    await db.refresh(feature)
    assert getattr(feature, edit) == changes[edit]
    assert feature.source_document_id is None
    assert source.digest_meta["project_training"]["status"] == "PROCESSING"


async def test_own_publication_is_reusable_until_next_manual_edit(feature_session):
    db = feature_session
    _project, source, _catalog, feature = await _source(db)
    assert feature is not None
    assert await auto_training_feature_intent_current(db, source)
    await publish_training_features(db, source)
    await db.commit()
    await db.refresh(feature)
    assert feature.value_text == "8 triệu đồng"
    assert feature.source_document_id == source.id
    assert source.metadata_["project_training"]["auto_feature_published_snapshot"]
    assert await auto_training_feature_intent_current(db, source)

    # An explicit retry can adopt only the profile this same source published.
    await publish_training_features(db, source)
    await db.commit()
    feature.value_text = "9 triệu đồng"
    await db.commit()
    assert not await auto_training_feature_intent_current(db, source)


async def test_catalog_read_backfill_does_not_supersede_auto_source(feature_session):
    db = feature_session
    project, source, _catalog, _feature = await _source(db, existing=False)
    assert source.metadata_["project_training"]["auto_feature_baseline"] == []
    await JobFeatureValueRepo(db).ensure_active_rows_for_project(project.id)
    assert await auto_training_feature_intent_current(db, source)
    await publish_training_features(db, source)
    await db.commit()
    assert await auto_training_feature_intent_current(db, source)


async def test_auto_source_without_capture_fails_closed(feature_session):
    db = feature_session
    _project, source, _catalog, feature = await _source(db)
    assert feature is not None
    training = dict(source.metadata_["project_training"])
    training.pop("auto_feature_baseline")
    source.metadata_ = {"project_training": training}
    await db.commit()
    assert not await auto_training_feature_intent_current(db, source)
    with pytest.raises(ConflictError):
        await publish_training_features(db, source)
    await db.refresh(feature)
    assert feature.value_text == "6 triệu đồng"


async def test_explicit_plan_keeps_existing_publication_semantics(feature_session):
    db = feature_session
    _project, source, _catalog, feature = await _source(db, auto=False)
    assert feature is not None
    feature.value_text = "7 triệu đồng"
    await db.commit()
    assert await auto_training_feature_intent_current(db, source)
    await publish_training_features(db, source)
    await db.commit()
    await db.refresh(feature)
    assert feature.value_text == "8 triệu đồng"
    assert "auto_feature_published_snapshot" not in source.metadata_["project_training"]


async def test_missing_source_feature_preserves_existing_value(feature_session):
    db = feature_session
    _project, source, catalog, feature = await _source(db)
    assert feature is not None
    source.metadata_ = {"project_training": {
        **source.metadata_["project_training"],
        "feature_values": [{"feature_id": str(catalog.id), "value": _prepared_value("", missing=True)}],
    }}
    await db.commit()
    await publish_training_features(db, source)
    await db.commit()
    await db.refresh(feature)
    assert feature.value_text == "6 triệu đồng"
    assert feature.source_document_id is None
    assert await auto_training_feature_intent_current(db, source)


async def test_manual_edit_during_auto_training_rolls_back_the_entire_publication(
    feature_session, monkeypatch
):
    db = feature_session
    actor, project, original = await _upload(db, monkeypatch)
    await _train(db, original)
    before_pointers = await _pointers(db, project.id)
    assert len(before_pointers) == 12 and all(before_pointers.values())

    async def jobs_snapshot():
        jobs = (await db.scalars(
            select(Job).join(Company).where(Company.project_id == project.id)
            .order_by(Job.id).execution_options(populate_existing=True)
        )).all()
        return [{column.name: getattr(job, column.name) for column in Job.__table__.columns} for job in jobs]

    before_jobs = await jobs_snapshot()
    assert before_jobs
    income = await db.scalar(
        select(JobFeatureValue).join(WorkerFeatureCatalog)
        .where(JobFeatureValue.project_id == project.id, WorkerFeatureCatalog.feature_key == "take_home_income")
    )
    assert income is not None
    replacement = await KnowledgeService(db).upload_bytes(
        "automatic-source.txt", "text/plain", _SOURCE.encode(),
        project_id=project.id, actor=actor, auto_extract=True,
    )
    assert replacement.id != original.id
    edited = False
    expected_features = None
    expected_card = None

    class EditingEmbedder(_Embedder):
        async def batch(self, texts):
            nonlocal edited, expected_features, expected_card
            if not edited and any(text.startswith("Vị trí") for text in texts):
                edited = True
                await ProjectFeatureService(db).update_feature(
                    project.id, income.id,
                    FeatureUpdate(value_text="Thu nhập đã xác minh 7 triệu đồng", evidence_text="Quản trị xác minh"),
                    actor,
                )
                await db.refresh(project)
                expected_card = dict(project.index_card)
                expected_features = await snapshot_feature_values(db, project.id)
                await db.commit()
            return await super().batch(texts)

    publish_attempted = False
    publish = category_batch.publish_training_features

    async def observe_atomic_publication(session, source):
        nonlocal publish_attempted
        publish_attempted = True
        # Exercise rollback after pointer and derived-job mutation, not merely
        # an early extraction guard that never enters the publication transaction.
        assert await _pointers(db, project.id) != before_pointers
        assert await jobs_snapshot() != before_jobs
        await publish(session, source)

    monkeypatch.setattr(category_batch, "publish_training_features", observe_atomic_publication)
    with pytest.raises(ConflictError, match="đã được chỉnh sửa"):
        await _train(db, replacement, embedder=EditingEmbedder())
    assert edited and publish_attempted
    await db.refresh(replacement)
    await db.refresh(project)
    assert replacement.status is KnowledgeStatus.FAILED
    assert replacement.digest_meta["project_training"]["status"] == "FAILED"
    assert await _pointers(db, project.id) == before_pointers
    assert await jobs_snapshot() == before_jobs
    assert project.index_card == expected_card
    assert await snapshot_feature_values(db, project.id) == expected_features
    assert not await auto_training_feature_intent_current(db, replacement)
