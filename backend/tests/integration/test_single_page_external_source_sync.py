from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.company import Project
from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeBaseMode
from app.models.single_page_external_source_sync_state import SinglePageExternalSourceSyncState
from app.models.user import Role, User
from app.schemas.knowledge_bases import DirectContextFileUpsert
from app.services.errors import ConflictError
from app.services.knowledge.external_source_sync import ExternalSourceSyncError
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.project.single_page_external_sources import (
    SinglePageExternalSourceService,
    sync_single_page_external_source,
)

pytestmark = pytest.mark.integration

SHEET_URL = "https://docs.google.com/spreadsheets/d/1rRk4wfKb90IxJAbywimgGDOV3Y7g8RbW1EpBabZmFw8/edit#gid=0"
FAQ_CSV = (
    "FAQ dự án LG Display dành cho BOT Chat Zalo,,,\n"
    "STT theo quy trình,Thông tin,Câu hỏi thường gặp,Thông tin trả lời\n"
    "1. Thông tin trước khi phỏng vấn,Độ tuổi,LG Display tuyển đến bao nhiêu tuổi?,Từ 18 tuổi trở lên.\n"
    "1. Thông tin trước khi phỏng vấn,Yêu cầu khi đi xin việc,Công ty có yêu cầu bằng cấp không?,Không yêu cầu bằng cấp.\n"
)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return 1

    async def eval(self, _script, _num_keys, key, owner):
        if self.store.get(key) != owner:
            return 0
        self.store.pop(key, None)
        return 1


async def _seed_project(integration_session):
    admin = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hash",
        role=Role.admin,
    )
    project = Project(
        slug=f"project-{uuid.uuid4().hex[:8]}",
        name="Direct Project",
        is_active=False,
        index_card={"summary": "Direct Project"},
    )
    integration_session.add_all([admin, project])
    await integration_session.flush()

    knowledge_base = KnowledgeBase(
        project_id=project.id,
        name="Direct Project Knowledge",
        slug=f"{project.slug}-kb",
        mode=KnowledgeBaseMode.DIRECT_CONTEXT,
        created_by=admin.id,
    )
    integration_session.add(knowledge_base)
    await integration_session.flush()
    project.knowledge_base_id = knowledge_base.id

    state = SinglePageExternalSourceSyncState(
        project_id=project.id,
        source_kind="google_sheet",
        sheet_url=SHEET_URL,
        sheet_gid=0,
        auto_sync_enabled=True,
        created_by=admin.id,
    )
    integration_session.add(state)
    await integration_session.commit()
    await integration_session.refresh(state)
    return admin, project, knowledge_base, state


@pytest.mark.asyncio
async def test_sync_success_noop_and_manual_edit_overwrite(
    integration_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin, project, knowledge_base, state = await _seed_project(integration_session)
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.get_redis",
        lambda: _FakeRedis(),
    )
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.SheetClient.fetch_csv",
        AsyncMock(return_value=FAQ_CSV),
    )
    monkeypatch.setattr(
        "app.services.knowledge_base_service.require_direct_context_ready",
        AsyncMock(return_value=None),
    )

    first = await sync_single_page_external_source(
        integration_session, state_id=state.id, actor=admin
    )
    assert first.status == "OK"
    direct_file = await integration_session.scalar(
        select(KnowledgeBaseDirectFile).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    assert direct_file is not None
    await integration_session.refresh(project)
    assert project.is_active is True
    first_hash = direct_file.content_sha256

    second = await sync_single_page_external_source(
        integration_session, state_id=state.id, actor=admin
    )
    assert second.status == "NO_OP"

    project.is_active = False
    await integration_session.commit()
    matching_inactive = await sync_single_page_external_source(
        integration_session, state_id=state.id, actor=admin
    )
    assert matching_inactive.status == "NO_OP"
    await integration_session.refresh(project)
    assert project.is_active is True

    await KnowledgeBaseService(integration_session).upsert_direct_file(
        knowledge_base.id,
        DirectContextFileUpsert(filename="manual.md", text="Nội dung chỉnh tay khác với sheet."),
        admin,
    )
    manual_hash = (
        await integration_session.scalar(
            select(KnowledgeBaseDirectFile.content_sha256).where(
                KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
            )
        )
    )
    assert manual_hash != first_hash

    third = await sync_single_page_external_source(
        integration_session, state_id=state.id, actor=admin
    )
    assert third.status == "OK"
    final_hash = (
        await integration_session.scalar(
            select(KnowledgeBaseDirectFile.content_sha256).where(
                KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
            )
        )
    )
    assert final_hash == first_hash


@pytest.mark.asyncio
async def test_oversized_sync_marks_failed_without_replacing_existing_page(
    integration_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin, project, knowledge_base, state = await _seed_project(integration_session)
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.get_redis",
        lambda: _FakeRedis(),
    )
    monkeypatch.setattr(
        "app.services.knowledge_base_service.require_direct_context_ready",
        AsyncMock(return_value=None),
    )
    await KnowledgeBaseService(integration_session).upsert_direct_file(
        knowledge_base.id,
        DirectContextFileUpsert(filename="existing.md", text="Nội dung đang hoạt động."),
        admin,
    )
    original_hash = await integration_session.scalar(
        select(KnowledgeBaseDirectFile.content_sha256).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.SheetClient.fetch_csv",
        AsyncMock(side_effect=ExternalSourceSyncError("sheet_too_large")),
    )

    outcome = await sync_single_page_external_source(
        integration_session, state_id=state.id, actor=admin
    )

    assert outcome.status == "FAILED"
    assert outcome.error == "sheet_too_large"
    assert await integration_session.scalar(
        select(KnowledgeBaseDirectFile.content_sha256).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    ) == original_hash
    await integration_session.refresh(project)
    assert project.is_active is False


@pytest.mark.asyncio
async def test_sync_failure_preserves_prior_page(
    integration_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin, _project, knowledge_base, state = await _seed_project(integration_session)
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.get_redis",
        lambda: _FakeRedis(),
    )
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.SheetClient.fetch_csv",
        AsyncMock(return_value=FAQ_CSV),
    )
    monkeypatch.setattr(
        "app.services.knowledge_base_service.require_direct_context_ready",
        AsyncMock(return_value=None),
    )

    await KnowledgeBaseService(integration_session).upsert_direct_file(
        knowledge_base.id,
        DirectContextFileUpsert(filename="seed.md", text="Trang cũ cần được giữ nguyên."),
        admin,
    )
    prior_text = await integration_session.scalar(
        select(KnowledgeBaseDirectFile.raw_text).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )

    monkeypatch.setattr(
        "app.services.knowledge_base_service.require_direct_context_ready",
        AsyncMock(side_effect=ConflictError("capacity check failed")),
    )
    outcome = await sync_single_page_external_source(
        integration_session, state_id=state.id, actor=admin
    )

    assert outcome.status == "FAILED"
    current_text = await integration_session.scalar(
        select(KnowledgeBaseDirectFile.raw_text).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    assert current_text == prior_text
    assert (
        await integration_session.scalar(
            select(SinglePageExternalSourceSyncState.last_status).where(
                SinglePageExternalSourceSyncState.id == state.id
            )
        )
    ) == "FAILED"


@pytest.mark.asyncio
async def test_activation_failure_rolls_back_replacement_and_stores_fixed_code(
    integration_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin, _project, knowledge_base, state = await _seed_project(integration_session)
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.get_redis", lambda: _FakeRedis()
    )
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.SheetClient.fetch_csv",
        AsyncMock(return_value=FAQ_CSV),
    )
    monkeypatch.setattr(
        "app.services.knowledge_base_service.require_direct_context_ready",
        AsyncMock(return_value=None),
    )
    await KnowledgeBaseService(integration_session).upsert_direct_file(
        knowledge_base.id,
        DirectContextFileUpsert(filename="existing.md", text="Trang cũ không được thay đổi."),
        admin,
    )
    prior = await integration_session.scalar(
        select(KnowledgeBaseDirectFile).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    assert prior is not None
    prior_hash, prior_text = prior.content_sha256, prior.raw_text
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources._stage_project_activation",
        AsyncMock(side_effect=RuntimeError("secret row contents must never persist")),
    )

    outcome = await sync_single_page_external_source(
        integration_session, state_id=state.id, actor=admin
    )

    assert outcome.status == "FAILED"
    assert outcome.error == "direct_file_update_failed"
    current = await integration_session.scalar(
        select(KnowledgeBaseDirectFile).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    assert current is not None
    assert (current.content_sha256, current.raw_text) == (prior_hash, prior_text)
    await integration_session.refresh(state)
    assert state.last_error == "direct_file_update_failed"


@pytest.mark.asyncio
async def test_deleting_source_keeps_current_single_page(integration_session) -> None:
    admin, _project, knowledge_base, state = await _seed_project(integration_session)
    await KnowledgeBaseService(integration_session).upsert_direct_file(
        knowledge_base.id,
        DirectContextFileUpsert(filename="current.md", text="Trang hiện tại vẫn được giữ."),
        admin,
    )
    state_id = state.id

    await SinglePageExternalSourceService(integration_session).delete_source(
        state.project_id, state_id, admin
    )

    assert await integration_session.get(SinglePageExternalSourceSyncState, state_id) is None
    current = await integration_session.scalar(
        select(KnowledgeBaseDirectFile).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    assert current is not None
    assert current.raw_text == "Trang hiện tại vẫn được giữ."
