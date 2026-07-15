"""Safe immutable persona-version selection metadata transport."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.api import personas
from app.api.dependencies import require_admin


def test_persona_versions_route_uses_exact_admin_path_and_rbac() -> None:
    route = next(
        route
        for route in personas.versions_router.routes
        if route.path == "/personas/{persona_id}/versions"
    )
    assert any(dependency.call is require_admin for dependency in route.dependant.dependencies)


async def test_persona_versions_response_excludes_body_and_followup_rules(monkeypatch) -> None:
    version = SimpleNamespace(
        id=uuid.uuid4(),
        version_no=2,
        checksum="a" * 64,
        created_at=datetime.now(UTC),
        body_md="private persona content",
        followup_rules={"private": True},
    )

    async def list_versions(_self, _persona_id):
        return [version]

    monkeypatch.setattr(personas.PersonaService, "list_versions", list_versions)
    response = await personas.list_persona_versions(
        persona_id=uuid.uuid4(),
        _admin=SimpleNamespace(),
        db=object(),
    )
    payload = response.model_dump(mode="json")
    assert set(payload["data"][0]) == {"id", "version_no", "checksum", "created_at"}
    assert "private persona content" not in str(payload)
