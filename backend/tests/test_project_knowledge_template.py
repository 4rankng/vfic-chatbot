"""The combined KB template: one document teaching recruiters the whole project.

Operator rule 2026-10-01: the markdown template must contain ALL project
categories together with the leading questions candidates ask in each one —
not a single jobs file an operator has to discover the other eleven from.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

from fastapi import FastAPI
from fastapi.params import Depends
from fastapi.testclient import TestClient
import pytest

from app.api import projects
from app.api.auth_dependencies import get_current_user, require_recruiter
from app.api.projects import get_project_knowledge_template
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
    build_project_knowledge_template,
)


def test_full_template_route_requires_recruiter() -> None:
    dependency = inspect.signature(get_project_knowledge_template).parameters["_user"].default

    assert isinstance(dependency, Depends)
    assert dependency.dependency is require_recruiter


def test_full_template_openapi_declares_text_instead_of_json() -> None:
    app = FastAPI()
    app.include_router(projects.router)

    operation = app.openapi()["paths"][
        "/knowledge/projects/{project_id}/knowledge-template"
    ]["get"]
    content = operation["responses"]["200"]["content"]

    assert set(content) == {"text/plain"}
    assert content["text/plain"]["schema"] == {"type": "string"}


@pytest.mark.parametrize("role", ["admin", "recruiter"])
def test_template_download_returns_markdown_attachment_for_authenticated_user(
    monkeypatch, role,
):
    app = FastAPI()
    app.include_router(projects.router)
    app.dependency_overrides[projects.get_project_knowledge_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role)
    catalog = AsyncMock(return_value=[])
    monkeypatch.setattr(
        projects, "KnowledgeCategoryService",
        lambda _db: SimpleNamespace(list_catalog=catalog),
    )
    project_id = uuid.uuid4()

    with TestClient(app) as client:
        response = client.get(f"/knowledge/projects/{project_id}/knowledge-template")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="mau-kb-du-an.md"'
    )
    assert response.text == build_project_knowledge_template()
    catalog.assert_awaited_once_with(project_id)


def test_full_template_contains_every_category_in_canonical_order() -> None:
    template = build_project_knowledge_template()

    offsets = [
        template.find(f"category: {definition.key.value}")
        for definition in CATEGORY_DEFINITIONS
    ]
    assert all(offset != -1 for offset in offsets)
    assert offsets == sorted(offsets)


def test_full_template_carries_leading_questions_per_category() -> None:
    template = build_project_knowledge_template()

    for definition in CATEGORY_DEFINITIONS:
        for question in definition.leading_questions:
            assert question in template
    # The fill-and-upload workflow header teaches the contract.
    assert "GIỮ NGUYÊN dòng frontmatter" in template
    # The filename rides the HTTP Content-Disposition header, not the content.
    assert "mau-kb-du-an.md" not in template
