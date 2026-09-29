"""Composition root for project/knowledge use cases and concrete adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.project_knowledge.application.providers import KnowledgeProviderFactory
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


def build_default_embedder(*, openrouter_api_key: str) -> Any:
    """The OpenRouter embedder.

    ``openrouter_api_key`` is REQUIRED and is expected to be the value the
    admin settings page stores (``IntegrationSettingsService.resolve_openrouter``).
    It used to be optional, which silently fell back to a process env var and
    let a key set in the UI go unused here.
    """
    from app.graph.clients import build_embedder

    return build_embedder(openrouter_api_key=openrouter_api_key)


def build_knowledge_provider_factory() -> KnowledgeProviderFactory:
    return GraphKnowledgeProviderFactory()


def build_knowledge_ingestion(db: AsyncSession) -> SqlAlchemyKnowledgeIngestionAdapter:
    return SqlAlchemyKnowledgeIngestionAdapter(
        db,
        providers=build_knowledge_provider_factory(),
    )


__all__ = [
    "GraphKnowledgeProviderFactory",
    "build_default_embedder",
    "build_knowledge_ingestion",
    "build_knowledge_provider_factory",
]
