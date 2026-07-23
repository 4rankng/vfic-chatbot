"""Composition root for project/knowledge use cases and concrete adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.project_knowledge.application.categories import CategoryUseCases
from app.project_knowledge.application.providers import KnowledgeProviderFactory
from app.project_knowledge.application.ingestion import KnowledgeIngestionUseCases
from app.project_knowledge.infrastructure.categories import SqlAlchemyCategoryAdapter
from app.project_knowledge.infrastructure.cache import RedisProjectKnowledgeCacheRepair
from app.composition.project_knowledge_jobs import build_project_knowledge_jobs
from app.project_knowledge.infrastructure.ingestion import SqlAlchemyKnowledgeIngestionAdapter


class GraphKnowledgeProviderFactory:
    """Adapt the current graph-owned provider builders at the composition boundary."""

    def embedder(self, *, openrouter_api_key: str) -> Any:
        from app.graph.clients import build_embedder

        return build_embedder(openrouter_api_key=openrouter_api_key)

    def json_extractor(
        self,
        *,
        minimax_api_key: str,
        openrouter_api_key: str,
    ) -> Any:
        from app.graph.factories import make_minimax_llm_json

        return make_minimax_llm_json(
            minimax_api_key=minimax_api_key,
            openrouter_api_key=openrouter_api_key,
        )


def build_default_embedder() -> Any:
    from app.graph.clients import build_embedder

    return build_embedder()


def build_knowledge_provider_factory() -> KnowledgeProviderFactory:
    return GraphKnowledgeProviderFactory()


def build_category_use_cases(db: AsyncSession) -> CategoryUseCases:
    return CategoryUseCases(
        SqlAlchemyCategoryAdapter(
            db,
            jobs=build_project_knowledge_jobs(),
            cache_repair=RedisProjectKnowledgeCacheRepair(),
        )
    )


def build_knowledge_ingestion_use_cases(db: AsyncSession) -> KnowledgeIngestionUseCases:
    return KnowledgeIngestionUseCases(
        SqlAlchemyKnowledgeIngestionAdapter(
            db,
            providers=build_knowledge_provider_factory(),
        )
    )


__all__ = [
    "GraphKnowledgeProviderFactory",
    "build_default_embedder",
    "build_category_use_cases",
    "build_knowledge_ingestion_use_cases",
    "build_knowledge_provider_factory",
]
