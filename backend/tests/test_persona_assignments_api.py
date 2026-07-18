"""Transport tests for provider-scoped persona assignment endpoints."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import personas
from app.api.dependencies import require_admin
from app.schemas.personas import PersonaAssignmentOut, PersonaAssignmentUpdate


def test_persona_assignments_routes_use_exact_admin_paths_and_rbac() -> None:
    paths = {
        route.path: route
        for route in personas.assignments_router.routes
    }
    assert "/knowledge/persona-assignments" in paths
    assert "/knowledge/persona-assignments/{provider}" in paths
    for route in paths.values():
        assert any(dependency.call is require_admin for dependency in route.dependant.dependencies)


@pytest.mark.asyncio
async def test_list_persona_assignments_returns_provider_rows(monkeypatch) -> None:
    rows = [
        PersonaAssignmentOut(
            provider="zalo_bot",
            label="Zalo Bot",
            persona_id=None,
            effective_persona_id=uuid.uuid4(),
            is_default=True,
        )
    ]

    async def list_adapter_assignments(_self):
        return rows

    monkeypatch.setattr(personas.PersonaService, "list_adapter_assignments", list_adapter_assignments)
    response = await personas.list_persona_assignments(_admin=SimpleNamespace(), db=object())

    assert response.model_dump(mode="json") == {"data": [rows[0].model_dump(mode="json")]}


@pytest.mark.asyncio
async def test_update_persona_assignment_surfaces_invalid_provider_as_422(monkeypatch) -> None:
    async def update_adapter_assignment(_self, provider, body, admin):  # noqa: ARG001
        raise ValueError("Unsupported adapter provider")

    monkeypatch.setattr(personas.PersonaService, "update_adapter_assignment", update_adapter_assignment)

    with pytest.raises(HTTPException) as exc:
        await personas.update_persona_assignment(
            provider="invalid",
            body=PersonaAssignmentUpdate(persona_id=None),
            admin=SimpleNamespace(),
            db=object(),
        )

    assert exc.value.status_code == 422
