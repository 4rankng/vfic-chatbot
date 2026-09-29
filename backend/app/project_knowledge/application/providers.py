"""Provider construction port for project/knowledge use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.project_knowledge.domain.embedding import EmbeddingRuntimeConfig


class KnowledgeProviderFactory(Protocol):
    def embedder(self, *, embedding: "EmbeddingRuntimeConfig") -> Any: ...

    def json_extractor(
        self,
        *,
        minimax_api_key: str,
        openrouter_api_key: str,
    ) -> Any: ...


__all__ = ["KnowledgeProviderFactory"]

