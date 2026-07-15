"""Real FastAPI dependency-order proofs for dormant generic routes."""

from types import SimpleNamespace

import httpx
from fastapi import Depends, FastAPI

from app.api.dependencies import get_current_user, require_capability
from app.core.db import get_db
from app.services.installation.service import InstallationService


def _isolated_app(repository_calls: list[str]) -> FastAPI:
    app = FastAPI()

    @app.get("/hidden", dependencies=[Depends(require_capability("conversation"))])
    async def hidden() -> dict[str, bool]:
        repository_calls.append("called")
        return {"ok": True}

    return app


async def test_unauthenticated_request_stops_before_installation_and_repository(
    monkeypatch,
) -> None:
    installation_calls: list[str] = []
    repository_calls: list[str] = []

    async def should_not_resolve(_self):
        installation_calls.append("called")
        raise AssertionError("installation must not resolve before authentication")

    monkeypatch.setattr(InstallationService, "require_active", should_not_resolve)
    app = _isolated_app(repository_calls)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/hidden")

    assert response.status_code == 401
    assert installation_calls == []
    assert repository_calls == []


async def test_disabled_capability_stops_before_repository(monkeypatch) -> None:
    repository_calls: list[str] = []
    installation_calls: list[str] = []

    async def authenticated_user():
        return SimpleNamespace(id="viewer")

    async def fake_db():
        yield SimpleNamespace()

    async def active_without_capability(_self):
        installation_calls.append("called")
        return SimpleNamespace(revision=SimpleNamespace(capability_ids=["knowledge"]))

    monkeypatch.setattr(InstallationService, "require_active", active_without_capability)
    app = _isolated_app(repository_calls)
    app.dependency_overrides[get_current_user] = authenticated_user
    app.dependency_overrides[get_db] = fake_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/hidden")

    assert response.status_code == 404
    assert installation_calls == ["called"]
    assert repository_calls == []
