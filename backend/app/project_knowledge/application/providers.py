"""Provider construction port for project/knowledge use cases."""

from __future__ import annotations

from typing import Any, Protocol


class KnowledgeProviderFactory(Protocol):
    def embedder(self, *, openrouter_api_key: str) -> Any: ...

    def json_extractor(
        self,
        *,
        minimax_api_key: str,
        openrouter_api_key: str,
    ) -> Any: ...


__all__ = ["KnowledgeProviderFactory"]

