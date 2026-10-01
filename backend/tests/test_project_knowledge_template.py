"""The combined KB template: one document teaching recruiters the whole project.

Operator rule 2026-10-01: the markdown template must contain ALL project
categories together with the leading questions candidates ask in each one —
not a single jobs file an operator has to discover the other eleven from.
"""

from __future__ import annotations

import inspect

from fastapi.params import Depends

from app.api.auth_dependencies import require_recruiter
from app.api.projects import get_project_knowledge_template
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
    build_project_knowledge_template,
)


def test_full_template_route_requires_recruiter() -> None:
    dependency = inspect.signature(get_project_knowledge_template).parameters["_user"].default

    assert isinstance(dependency, Depends)
    assert dependency.dependency is require_recruiter


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
