"""Composition root for project/knowledge use cases and concrete adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.project_knowledge.application.providers import KnowledgeProviderFactory
from app.project_knowledge.domain.embedding import EmbeddingRuntimeConfig
from app.project_knowledge.infrastructure.ingestion import SqlAlchemyKnowledgeIngestionAdapter


class GraphKnowledgeProviderFactory:
    """Adapt the current graph-owned provider builders at the composition boundary."""

    def embedder(self, *, embedding: EmbeddingRuntimeConfig) -> Any:
        from app.graph.clients import build_embedder

        return build_embedder(
            provider=embedding.provider,
            openrouter_api_key=embedding.openrouter_api_key,
            gemini_api_key=embedding.gemini_api_key,
        )

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


def build_default_embedder(*, embedding: EmbeddingRuntimeConfig) -> Any:
    """The embedder for the provider the Settings page selects.

    ``embedding`` is REQUIRED and is expected to come from
    ``IntegrationSettingsService.resolve_embedding``. It used to be an
    optional OpenRouter key with a process-env fallback, which both let a key
    set in the UI go unused and hardwired the provider.
    """
    from app.graph.clients import build_embedder

    return build_embedder(
        provider=embedding.provider,
        openrouter_api_key=embedding.openrouter_api_key,
        gemini_api_key=embedding.gemini_api_key,
    )


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
