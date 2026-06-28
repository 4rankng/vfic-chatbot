"""Regression: a canonical-uploaded bus timetable is reachable by the agent.

Guards migration 0011 + the repository NULL ``p_project_slug`` change. Before the
fix, canonical VFIC Knowledge Markdown v1 was persisted under ``projects.slug`` =
the frontmatter ``project_slug`` ('lg-display'), while ``search_bus_timetable``
hardcoded tenant 'vfic' -> the agent got 0 rows for any canonical timetable.
"""
from __future__ import annotations

import pytest

from app.models.knowledge import KnowledgeStatus
from app.services.knowledge.canonical import load_template
from app.services.knowledge.pipeline import KnowledgePipeline
from app.services.knowledge_service import KnowledgeService
from app.services.retrieval import RetrievalRepository

VEC = [0.01] * 3072


class _FakeEmbedder:
    async def embed(self, _t):
        return list(VEC)

    async def batch(self, texts):
        return [list(VEC) for _ in texts]

    __call__ = embed


async def _guard_llm(_system: str, _user: str) -> str:
    # Canonical ingest must bypass MiniMax entirely; if the pipeline calls this,
    # the fast-path gating in pipeline.py has regressed.
    raise AssertionError("canonical ingest must not call the LLM")


@pytest.mark.asyncio
async def test_canonical_bus_timetable_is_reachable_by_agent(db_session, clean_kb):
    doc = await KnowledgeService(db_session).upload_bytes(
        "canonical-bus.md",
        "text/markdown",
        load_template().encode("utf-8"),
        require_canonical=True,
    )
    await KnowledgePipeline(db_session, _FakeEmbedder(), _guard_llm).run(doc)
    await db_session.refresh(doc)

    # Sanity: the canonical fast path published without calling the LLM.
    assert doc.status == KnowledgeStatus.PUBLISHED

    rows = await RetrievalRepository(db_session).search_bus_timetable(
        company="LG Display", question="td plaza", limit=20
    )

    assert rows, (
        "agent should retrieve the canonical LG Display 'TD Plaza' route; "
        "a NULL project-slug filter is required for canonical timetables"
    )
    assert any("TD Plaza" == (getattr(r, "route_name", "") or "") for r in rows)
