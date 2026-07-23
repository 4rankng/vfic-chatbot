"""Real FastAPI dependency-order proofs for dormant generic routes."""

from types import SimpleNamespace

import httpx
from fastapi import Depends, FastAPI

from app.api.auth_dependencies import get_current_user
from app.api.installation_dependencies import require_capability, require_capability_or_legacy
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


def test_recruitment_routes_declare_their_capability_guards() -> None:
    from app.api.jobs import router as jobs_router
    from app.api.leads import router as leads_router

    lead_dependencies = {
        dependency.dependency.__name__
        for route in leads_router.routes
        for dependency in route.dependencies
        if dependency.dependency is not None
    }
    job_dependencies = {
        dependency.dependency.__name__
        for route in jobs_router.routes
        for dependency in route.dependencies
        if dependency.dependency is not None
    }

    assert "require_capability_or_legacy_candidate_intake" in lead_dependencies
    assert "require_capability_or_legacy_job_advisory" in job_dependencies


async def test_legacy_recruitment_route_remains_available_without_installation_state(
    monkeypatch,
) -> None:
    repository_calls: list[str] = []

    app = FastAPI()

    @app.get(
        "/legacy",
        dependencies=[Depends(require_capability_or_legacy("candidate_intake"))],
    )
    async def legacy() -> dict[str, bool]:
        return {"ok": True}

    async def authenticated_user():
        return SimpleNamespace(id="viewer")

    async def fake_db():
        yield SimpleNamespace()

    async def no_active_installation(_self):
        return None

    async def no_installation_state(_self):
        repository_calls.append("called")
        return None

    monkeypatch.setattr(InstallationService, "resolve_active", no_active_installation)
    monkeypatch.setattr(
        "app.services.installation.repository.InstallationRepository.get_state",
        no_installation_state,
    )
    app.dependency_overrides[get_current_user] = authenticated_user
    app.dependency_overrides[get_db] = fake_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/legacy")

    assert response.status_code == 200
    assert repository_calls == ["called"]


async def test_legacy_route_is_hidden_after_installation_adoption(monkeypatch) -> None:
    app = FastAPI()

    @app.get(
        "/legacy",
        dependencies=[Depends(require_capability_or_legacy("candidate_intake"))],
    )
    async def legacy() -> dict[str, bool]:
        return {"ok": True}

    async def authenticated_user():
        return SimpleNamespace(id="viewer")

    async def fake_db():
        yield SimpleNamespace()

    async def no_active_installation(_self):
        return None

    async def configured_installation_state(_self):
        return SimpleNamespace(lifecycle="draft")

    monkeypatch.setattr(InstallationService, "resolve_active", no_active_installation)
    monkeypatch.setattr(
        "app.services.installation.repository.InstallationRepository.get_state",
        configured_installation_state,
    )
    app.dependency_overrides[get_current_user] = authenticated_user
    app.dependency_overrides[get_db] = fake_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/legacy")

    assert response.status_code == 404
