"""Category migration keeps candidate-facing authority until explicit cutover."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from app.models.knowledge import KnowledgeBaseMode, KnowledgeCategoryRevisionStatus
from app.project_knowledge.domain.category_catalog import CATEGORY_DEFINITIONS
from app.services.knowledge.category_authority import (
    _categories_missing_an_active_revision,
    category_projection_allowed,
)


@pytest.mark.parametrize(
    "authority,mode,expected",
    [(False, KnowledgeBaseMode.RAG, False), (False, KnowledgeBaseMode.DIRECT_CONTEXT, False),
     (True, KnowledgeBaseMode.DIRECT_CONTEXT, False), (True, KnowledgeBaseMode.RAG, True)],
)
async def test_empty_card_does_not_establish_category_authority(authority, mode, expected):
    project = SimpleNamespace(
        category_authority_started=authority, index_card={}, knowledge_base_id=uuid.uuid4(),
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(mode=mode, id=project.knowledge_base_id)),
        scalar=AsyncMock(return_value=uuid.uuid4()),
    )
    assert await category_projection_allowed(db, project) is expected


@pytest.mark.parametrize("status", [
    KnowledgeCategoryRevisionStatus.STAGED, KnowledgeCategoryRevisionStatus.FAILED,
    KnowledgeCategoryRevisionStatus.ARCHIVED,
])
async def test_cutover_rejects_an_unready_active_pointer(status):
    categories = [SimpleNamespace(
        id=uuid.uuid4(), category_key=definition.key.value, active_revision_id=None,
    ) for definition in CATEGORY_DEFINITIONS]
    categories[0].active_revision_id = uuid.uuid4()
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(category_id=categories[0].id, status=status)),
        scalar=AsyncMock(return_value=SimpleNamespace(status=KnowledgeCategoryRevisionStatus.CLEARED)),
    )
    assert await _categories_missing_an_active_revision(db, categories) == ["jobs"]


async def test_cutover_rejects_another_categorys_revision():
    categories = [SimpleNamespace(
        id=uuid.uuid4(), category_key=definition.key.value, active_revision_id=None,
    ) for definition in CATEGORY_DEFINITIONS]
    categories[0].active_revision_id = uuid.uuid4()
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(
            category_id=uuid.uuid4(), status=KnowledgeCategoryRevisionStatus.ACTIVE,
        )),
        scalar=AsyncMock(return_value=SimpleNamespace(status=KnowledgeCategoryRevisionStatus.CLEARED)),
    )
    assert await _categories_missing_an_active_revision(db, categories) == ["jobs"]
