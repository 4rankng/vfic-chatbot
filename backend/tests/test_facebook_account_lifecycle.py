from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.channels.providers import facebook_account as facebook_account_mod
from app.models.channel_account import ChannelAccount


class _LifecycleDb:
    def __init__(self, *scalar_results):
        self._scalar_results = list(scalar_results)
        self.events: list[str] = []
        self.added: list[object] = []
        self.flush = AsyncMock(side_effect=self._flush)
        self.commit = AsyncMock(side_effect=self._commit)
        self.rollback = AsyncMock()

    async def scalar(self, _query):
        if not self._scalar_results:
            return None
        return self._scalar_results.pop(0)

    def add(self, row) -> None:
        self.added.append(row)

    async def _flush(self) -> None:
        self.events.append("flush")

    async def _commit(self) -> None:
        self.events.append("commit")


@pytest.mark.asyncio
async def test_activation_collision_retries_without_standalone_winner_commit(
    monkeypatch,
) -> None:
    db = _LifecycleDb()
    lifecycle = facebook_account_mod.FacebookPageLifecycle(db)
    winner = object()
    activate_once = AsyncMock(
        side_effect=[IntegrityError("insert", {}, RuntimeError("collision")), winner]
    )
    monkeypatch.setattr(lifecycle, "_activate_once", activate_once)

    result = await lifecycle.activate_or_reactivate(
        page_id="page-123",
        page_name="Page 123",
        page_access_token="token-123",
        admin_id="admin-1",
    )

    assert result is winner
    assert activate_once.await_count == 2
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_activate_reactivate_commits_once_after_token_stage_and_audit(
    monkeypatch,
):
    class _FakeSettingsService:
        def __init__(self, db):
            self.db = db

        async def stage_facebook_page_token_upsert(
            self, page_id: str, token: str, *, updated_by
        ) -> None:
            assert (page_id, token, updated_by) == ("page-123", "token-123", "admin-1")
            assert self.db.commit.await_count == 0
            self.db.events.append("stage_upsert")

        async def invalidate_facebook_cache(self, *, best_effort: bool) -> None:
            assert best_effort is True
            assert self.db.commit.await_count == 1
            self.db.events.append("invalidate")

    async def fake_record_audit(db, **_kwargs):
        assert db.commit.await_count == 0
        db.events.append("audit")

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService",
        _FakeSettingsService,
    )
    monkeypatch.setattr(facebook_account_mod, "record_audit", fake_record_audit)

    db = _LifecycleDb(None, None)

    account = await facebook_account_mod.FacebookPageLifecycle(db).activate_or_reactivate(
        page_id="page-123",
        page_name="Page 123",
        page_access_token="token-123",
        admin_id="admin-1",
    )

    assert account.account_key == "page-123"
    assert account.status == "ACTIVE"
    assert db.commit.await_count == 1
    assert db.events == ["flush", "stage_upsert", "audit", "commit", "invalidate"]


@pytest.mark.asyncio
async def test_disconnect_commits_once_after_token_stage_delete_and_audit(monkeypatch):
    account = ChannelAccount(
        provider="facebook_messenger",
        account_key="page-123",
        label="Page 123",
        status="ACTIVE",
        generation=3,
    )

    class _FakeSettingsService:
        def __init__(self, db):
            self.db = db

        async def stage_facebook_page_token_delete(self, page_id: str) -> None:
            assert page_id == "page-123"
            assert self.db.commit.await_count == 0
            self.db.events.append("stage_delete")

        async def invalidate_facebook_cache(self, *, best_effort: bool) -> None:
            assert best_effort is True
            assert self.db.commit.await_count == 1
            self.db.events.append("invalidate")

    async def fake_record_audit(db, **_kwargs):
        assert db.commit.await_count == 0
        db.events.append("audit")

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService",
        _FakeSettingsService,
    )
    monkeypatch.setattr(facebook_account_mod, "record_audit", fake_record_audit)

    db = _LifecycleDb(account)

    disconnected = await facebook_account_mod.FacebookPageLifecycle(db).disconnect(
        page_id="page-123",
        admin_id="admin-1",
    )

    assert disconnected is account
    assert disconnected.status == "INACTIVE"
    assert db.commit.await_count == 1
    assert db.events == ["flush", "stage_delete", "audit", "commit", "invalidate"]


@pytest.mark.asyncio
async def test_activate_reactivate_does_not_commit_when_stage_write_fails(monkeypatch):
    class _FakeSettingsService:
        def __init__(self, db):
            self.db = db

        async def stage_facebook_page_token_upsert(
            self, _page_id: str, _token: str, *, updated_by
        ) -> None:
            assert updated_by == "admin-1"
            raise RuntimeError("stage failed")

        async def invalidate_facebook_cache(self, *, best_effort: bool) -> None:
            raise AssertionError("cache invalidation must not run after stage failure")

    async def fake_record_audit(_db, **_kwargs):
        raise AssertionError("audit must not run after stage failure")

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService",
        _FakeSettingsService,
    )
    monkeypatch.setattr(facebook_account_mod, "record_audit", fake_record_audit)

    db = _LifecycleDb(None, None)

    with pytest.raises(RuntimeError, match="stage failed"):
        await facebook_account_mod.FacebookPageLifecycle(db).activate_or_reactivate(
            page_id="page-123",
            page_name="Page 123",
            page_access_token="token-123",
            admin_id="admin-1",
        )

    assert db.commit.await_count == 0


@pytest.mark.asyncio
async def test_activate_reactivate_does_not_commit_when_audit_fails(monkeypatch):
    class _FakeSettingsService:
        def __init__(self, db):
            self.db = db

        async def stage_facebook_page_token_upsert(
            self, _page_id: str, _token: str, *, updated_by
        ) -> None:
            assert updated_by == "admin-1"
            assert self.db.commit.await_count == 0
            self.db.events.append("stage_upsert")

        async def invalidate_facebook_cache(self, *, best_effort: bool) -> None:
            raise AssertionError("cache invalidation must not run after audit failure")

    async def fake_record_audit(db, **_kwargs):
        assert db.commit.await_count == 0
        db.events.append("audit")
        raise RuntimeError("audit failed")

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService",
        _FakeSettingsService,
    )
    monkeypatch.setattr(facebook_account_mod, "record_audit", fake_record_audit)

    db = _LifecycleDb(None, None)

    with pytest.raises(RuntimeError, match="audit failed"):
        await facebook_account_mod.FacebookPageLifecycle(db).activate_or_reactivate(
            page_id="page-123",
            page_name="Page 123",
            page_access_token="token-123",
            admin_id="admin-1",
        )

    assert db.commit.await_count == 0
    assert db.events == ["flush", "stage_upsert", "audit"]
