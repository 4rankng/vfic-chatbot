from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import BigInteger
from pydantic import ValidationError

from app.models.single_page_external_source_sync_state import SinglePageExternalSourceSyncState
from app.services.knowledge.external_source_sync import ExternalSourceSyncError
from app.services.errors import UpstreamError
from app.schemas.project_single_page_sync import SinglePageExternalSourceCreate
from app.services.project.single_page_external_sources import (
    SinglePageExternalSourceService,
    SinglePageExternalSourceSyncOutcome,
    parse_sheet_gid,
    render_sheet_markdown,
    sync_single_page_external_source,
)
from app.services.project import single_page_external_sources as single_page_sync

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "external_source_sync"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1rRk4wfKb90IxJAbywimgGDOV3Y7g8RbW1EpBabZmFw8/edit"


class _Db:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed: list[object] = []
        self.deleted: list[object] = []

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, value) -> None:
        self.refreshed.append(value)

    async def delete(self, value) -> None:
        self.deleted.append(value)


class _FakeRedis:
    def __init__(self, *, acquire: bool = True) -> None:
        self.acquire = acquire
        self.deleted: list[str] = []

    async def set(self, *_args, **_kwargs):
        return self.acquire or None

    async def delete(self, key):
        self.deleted.append(key)
        return 1

    async def eval(self, _script, _num_keys, key, owner):
        return 1


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_gid_parser_prefers_fragment_over_query() -> None:
    gid = parse_sheet_gid(f"{SHEET_URL}?gid=7#gid=42")
    assert gid == 42


def test_gid_parser_falls_back_to_query_when_fragment_has_no_gid() -> None:
    gid = parse_sheet_gid(f"{SHEET_URL}?gid=99#sheet=overview")
    assert gid == 99


@pytest.mark.parametrize(
    ("url", "code"),
    [
        (SHEET_URL, "missing_gid"),
        (f"{SHEET_URL}#gid=-1", "invalid_gid"),
        (f"{SHEET_URL}#gid=abc", "invalid_gid"),
        (f"{SHEET_URL}#gid=1&gid=2", "conflicting_gid"),
        (f"{SHEET_URL}#gid=9007199254740992", "unsafe_gid"),
        (f"{SHEET_URL}?gid=7#gid=", "invalid_gid"),
    ],
)
def test_gid_parser_rejects_invalid_inputs(url: str, code: str) -> None:
    with pytest.raises(ExternalSourceSyncError, match=code):
        parse_sheet_gid(url)


def test_render_sheet_markdown_is_deterministic() -> None:
    markdown, row_count = render_sheet_markdown(_read("faq_sheet_four_column.csv"))
    assert row_count == 3
    assert markdown.startswith("# Câu hỏi thường gặp\n\n## FAQ\n")
    assert "### FAQ: LG Display tuyển đến bao nhiêu tuổi?" in markdown
    assert "Tags: Thông tin trước khi phỏng vấn, Độ tuổi" in markdown
    assert markdown.endswith("\n")


def test_model_uses_bigint_gid_and_project_unique_constraint() -> None:
    column = SinglePageExternalSourceSyncState.__table__.columns["sheet_gid"]
    assert isinstance(column.type, BigInteger)
    constraints = {
        name
        for name in (
            constraint.name
            for constraint in SinglePageExternalSourceSyncState.__table__.constraints
            if constraint.name
        )
    }
    assert "uq_single_page_external_source_per_project_source" in constraints


def test_create_schema_accepts_512_character_url_and_rejects_513() -> None:
    SinglePageExternalSourceCreate(sheet_url="x" * 512)
    with pytest.raises(ValidationError):
        SinglePageExternalSourceCreate(sheet_url="x" * 513)


@pytest.mark.asyncio
async def test_create_source_compensates_when_enqueue_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Db()
    service = SinglePageExternalSourceService(db)
    service._require_direct_context_project = AsyncMock(
        return_value=(SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4()))
    )
    audit = AsyncMock()
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.record_audit",
        audit,
    )
    monkeypatch.setattr(
        "app.workers.single_page_external_source_sync_worker.enqueue_one_shot",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(UpstreamError, match="single_page_sync_enqueue_failed"):
        await service.create_source(
            uuid.uuid4(),
            SimpleNamespace(sheet_url=f"{SHEET_URL}#gid=0", auto_sync_enabled=True),
            SimpleNamespace(id=uuid.uuid4()),
        )

    assert len(db.deleted) == 1
    assert db.commits == 2
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_now_enqueue_failure_clears_cooldown_and_raises_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Db()
    service = SinglePageExternalSourceService(db)
    source_id = uuid.uuid4()
    service._load_source = AsyncMock(
        return_value=SimpleNamespace(id=source_id, project_id=uuid.uuid4())
    )
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.get_redis", lambda: fake_redis
    )
    monkeypatch.setattr(
        "app.workers.single_page_external_source_sync_worker.enqueue_one_shot",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(UpstreamError, match="single_page_sync_enqueue_failed"):
        await service.run_now(uuid.uuid4(), source_id, SimpleNamespace(id=uuid.uuid4()))

    assert fake_redis.deleted == [f"single-page-ext-src-run-now:{source_id}"]


@pytest.mark.asyncio
async def test_create_source_keeps_new_state_when_enqueue_receipt_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.utils import EnqueueStatusUnknown

    db = _Db()
    service = SinglePageExternalSourceService(db)
    service._require_direct_context_project = AsyncMock(
        return_value=(SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4()))
    )
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.record_audit", AsyncMock()
    )
    monkeypatch.setattr(
        "app.workers.single_page_external_source_sync_worker.enqueue_one_shot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(EnqueueStatusUnknown("job-1")),
    )

    row = await service.create_source(
        uuid.uuid4(),
        SimpleNamespace(sheet_url=f"{SHEET_URL}#gid=0", auto_sync_enabled=True),
        SimpleNamespace(id=uuid.uuid4()),
    )

    assert row.last_status == "NEW"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_run_now_ambiguous_receipt_keeps_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.utils import EnqueueStatusUnknown

    db = _Db()
    service = SinglePageExternalSourceService(db)
    source_id = uuid.uuid4()
    service._load_source = AsyncMock(return_value=SimpleNamespace(id=source_id))
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.get_redis", lambda: fake_redis
    )
    monkeypatch.setattr(
        "app.workers.single_page_external_source_sync_worker.enqueue_one_shot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(EnqueueStatusUnknown("job-2")),
    )

    with pytest.raises(UpstreamError, match="single_page_sync_enqueue_status_unknown"):
        await service.run_now(uuid.uuid4(), source_id, SimpleNamespace(id=uuid.uuid4()))

    assert fake_redis.deleted == []


@pytest.mark.asyncio
async def test_expired_lock_can_be_reacquired_without_old_owner_deleting_new_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_id = uuid.uuid4()
    state = SimpleNamespace(id=state_id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=state)

    class _ExpiringRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        async def set(self, key, value, *, nx=False, ex=None):
            if nx and key in self.store:
                return None
            self.store[key] = value
            return True

        async def eval(self, _script, _num_keys, key, owner):
            if self.store.get(key) != owner:
                return 0
            self.store.pop(key, None)
            return 1

    redis = _ExpiringRedis()
    lock_key = f"{single_page_sync.LOCK_KEY_PREFIX}:{state_id}"
    calls = 0

    async def _sync(_db, _state, _actor):
        nonlocal calls
        calls += 1
        if calls == 1:
            # Simulate TTL expiry and another worker acquiring before the old
            # worker's finally block runs.
            redis.store[lock_key] = "new-worker-owner"
        return SinglePageExternalSourceSyncOutcome(status="NO_OP")

    monkeypatch.setattr(single_page_sync, "get_redis", lambda: redis)
    monkeypatch.setattr(single_page_sync, "_sync_locked", _sync)

    await sync_single_page_external_source(db, state_id=state_id, actor=SimpleNamespace())
    assert redis.store[lock_key] == "new-worker-owner"

    redis.store.pop(lock_key)  # the replacement lock's TTL expires
    await sync_single_page_external_source(db, state_id=state_id, actor=SimpleNamespace())
    assert calls == 2
    assert lock_key not in redis.store
