from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import BigInteger

from app.models.single_page_external_source_sync_state import SinglePageExternalSourceSyncState
from app.services.knowledge.external_source_sync import ExternalSourceSyncError
from app.services.errors import UpstreamError
from app.services.project.single_page_external_sources import (
    SinglePageExternalSourceService,
    parse_sheet_gid,
    render_sheet_markdown,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "external_source_sync"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1rRk4wfKb90IxJAbywimgGDOV3Y7g8RbW1EpBabZmFw8/edit"


class _Db:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed: list[object] = []

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


class _FakeRedis:
    def __init__(self, *, acquire: bool = True) -> None:
        self.acquire = acquire
        self.deleted: list[str] = []

    async def set(self, *_args, **_kwargs):
        return self.acquire or None

    async def delete(self, key):
        self.deleted.append(key)
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


@pytest.mark.asyncio
async def test_create_source_persists_new_even_if_enqueue_fails(
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

    row = await service.create_source(
        uuid.uuid4(),
        SimpleNamespace(sheet_url=f"{SHEET_URL}#gid=0", auto_sync_enabled=True),
        SimpleNamespace(id=uuid.uuid4()),
    )

    assert row.last_status == "NEW"
    assert row.sheet_gid == 0
    assert db.commits == 1
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
