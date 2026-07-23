"""Transport guards for standalone knowledge-base administration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import knowledge_bases
from app.api.auth_dependencies import require_admin
from app.schemas.knowledge_bases import DirectContextFileUpsert


def test_every_knowledge_base_route_requires_admin() -> None:
    assert knowledge_bases.router.routes
    for route in knowledge_bases.router.routes:
        assert any(
            dependency.call is require_admin for dependency in route.dependant.dependencies
        ), route.path


def test_bootstrap_route_is_registered_before_id_routes() -> None:
    paths = [route.path for route in knowledge_bases.router.routes]
    assert paths.index("/knowledge-bases/bootstrap-legacy") < paths.index(
        "/knowledge-bases/{knowledge_base_id}"
    )


@pytest.mark.asyncio
async def test_project_owned_direct_file_uses_project_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_base_id = uuid.uuid4()
    project_id = uuid.uuid4()
    direct_file = SimpleNamespace(
        id=uuid.uuid4(),
        knowledge_base_id=knowledge_base_id,
        filename="rorze.md",
        char_count=42,
        line_count=1,
        content_sha256="a" * 64,
        updated_at=datetime.now(UTC),
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=project_id))
    actor = SimpleNamespace(id=uuid.uuid4())
    replace_single_page = AsyncMock(return_value=direct_file)
    project_service = SimpleNamespace(replace_single_page=replace_single_page)
    monkeypatch.setattr(knowledge_bases, "ProjectService", lambda _db: project_service)
    body = DirectContextFileUpsert(filename="rorze.md", text="Rorze recruitment knowledge")

    result = await knowledge_bases.upsert_direct_context_file(
        knowledge_base_id,
        body,
        admin=actor,
        db=db,
    )

    assert result.knowledge_base_id == knowledge_base_id
    replace_single_page.assert_awaited_once_with(project_id, body, actor)
