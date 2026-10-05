"""Web Push: the fan-out service, its dedupe, and the subscription API.

The triggers matter more than the transport here: an OA token that can never be
refreshed and a reply the provider refuses twice are both silent failures, so
these tests pin that the alert fires, fires once per window, and never breaks the
path it reports on.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from app.api.auth_dependencies import get_current_user
from app.api.notifications import router as notifications_router
from app.models.user import Role
from app.services.push import service as push
from app.shared.infrastructure.db import get_request_db

VIEWER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _viewer(role: Role = Role.admin) -> SimpleNamespace:
    return SimpleNamespace(id=VIEWER_ID, role=role, email="ops@test", full_name="Ops")


def _settings(*, with_keys: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        vapid_public_key="BEl62i-public" if with_keys else "",
        vapid_private_key="private" if with_keys else "",
        vapid_subject="mailto:ops@test",
    )


class _Redis:
    """Minimal SET NX EX stand-in."""

    def __init__(self, *, fail: bool = False) -> None:
        self.keys: set[str] = set()
        self.fail = fail

    async def set(self, key, _value, *, nx=False, ex=None):  # noqa: ANN001, ARG002
        if self.fail:
            raise RuntimeError("redis down")
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True


@pytest.fixture()
def settings(monkeypatch):
    stub = _settings()
    monkeypatch.setattr(push, "get_settings", lambda: stub)
    return stub


@pytest.mark.asyncio
async def test_push_is_disabled_without_a_vapid_pair(monkeypatch):
    monkeypatch.setattr(push, "get_settings", lambda: _settings(with_keys=False))

    assert push.push_enabled() is False
    assert await push.notify_admins(_session(), title="t", body="b", url="/", tag="x", dedupe_key="k") == 0


def _session() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


@pytest.mark.asyncio
async def test_alert_once_dedupes_within_the_window_and_fails_open(monkeypatch):
    redis = _Redis()
    monkeypatch.setattr(push, "get_redis", lambda: redis)

    assert await push.alert_once("zalo-oa-refresh:tingting") is True
    assert await push.alert_once("zalo-oa-refresh:tingting") is False
    assert await push.alert_once("reconcile-stuck:abc") is True

    monkeypatch.setattr(push, "get_redis", lambda: _Redis(fail=True))
    assert await push.alert_once("zalo-oa-refresh:tingting") is True  # fails open


@pytest.mark.asyncio
async def test_send_prunes_endpoints_the_browser_dropped(settings, monkeypatch):
    live = push.PushTarget(uuid.uuid4(), "https://push/live", "p1", "a1")
    dead = push.PushTarget(uuid.uuid4(), "https://push/gone", "p2", "a2")

    def fake_send(targets, payload):  # noqa: ANN001, ARG001
        assert [t.endpoint for t in targets] == ["https://push/live", "https://push/gone"]
        return [dead.id]

    monkeypatch.setattr(push, "_send_sync", fake_send)
    db = _session()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(all=lambda: [(live.id, live.endpoint, live.p256dh, live.auth), (dead.id, dead.endpoint, dead.p256dh, dead.auth)]),
            MagicMock(),
            MagicMock(),
        ]
    )

    assert await push.send_to_users(db, [VIEWER_ID], {"title": "t"}) == 1
    # One DELETE for the gone endpoint, one UPDATE for the live one, one commit.
    statements = [str(call.args[0]) for call in db.execute.await_args_list]
    assert any(statement.startswith("DELETE") for statement in statements)
    assert any(statement.startswith("UPDATE") for statement in statements)


@pytest.mark.asyncio
async def test_notify_admins_targets_only_active_admins(settings, monkeypatch):
    sent: list[list[uuid.UUID]] = []
    monkeypatch.setattr(push, "get_redis", lambda: _Redis())

    async def fake_send(db, user_ids, payload):  # noqa: ANN001, ARG001
        sent.append(list(user_ids))
        return len(user_ids)

    monkeypatch.setattr(push, "send_to_users", fake_send)
    db = _session()
    db.scalars = AsyncMock(return_value=[VIEWER_ID])

    count = await push.notify_admins(
        db, title="t", body="b", url="/", tag="tag", dedupe_key="k"
    )

    assert count == 1
    assert sent == [[VIEWER_ID]]
    query = str(db.scalars.await_args.args[0])
    assert "users.role" in query and "users.disabled" in query


def _api_client(
    monkeypatch,
    *,
    user: SimpleNamespace | None = None,
    db_query=None,
):
    app = FastAPI()
    app.include_router(notifications_router, prefix="/api/v1")

    async def override_user():
        return user if user is not None else _viewer()

    async def override_db():
        db = _session()
        if db_query is not None:
            db.scalars = AsyncMock(return_value=db_query)
        yield db

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_request_db] = override_db
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


@pytest.mark.asyncio
async def test_vapid_key_route_reports_whether_push_is_configured(monkeypatch):
    # The route reads both values through the push service, which owns the config.
    stub = _settings()
    monkeypatch.setattr(push, "get_settings", lambda: stub)

    async with _api_client(monkeypatch) as http:
        response = await http.get("/api/v1/notifications/vapid-public-key")

    assert response.status_code == 200
    assert response.json() == {"enabled": True, "key": "BEl62i-public"}


@pytest.mark.asyncio
async def test_subscribe_upserts_and_unsubscribe_deletes_for_the_caller(monkeypatch):
    async with _api_client(monkeypatch) as http:
        created = await http.post(
            "/api/v1/notifications/subscriptions",
            json={
                "endpoint": "https://push/abc",
                "keys": {"p256dh": "p", "auth": "a"},
                "user_agent": "Chrome",
            },
        )
        removed = await http.request(
            "DELETE",
            "/api/v1/notifications/subscriptions",
            json={"endpoint": "https://push/abc"},
        )

    assert created.status_code == 204
    assert removed.status_code == 204


@pytest.mark.asyncio
async def test_test_route_requires_configured_push_and_a_subscription(monkeypatch):
    monkeypatch.setattr("app.api.notifications.push_enabled", lambda: False)
    async with _api_client(monkeypatch) as http:
        missing_config = await http.post("/api/v1/notifications/test")
    assert missing_config.status_code == 503

    monkeypatch.setattr("app.api.notifications.push_enabled", lambda: True)
    async with _api_client(monkeypatch, db_query=[]) as http:
        no_subscription = await http.post("/api/v1/notifications/test")

    assert no_subscription.status_code == 409
