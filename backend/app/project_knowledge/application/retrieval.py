"""Provider-neutral query port owned by the project/knowledge context."""

from __future__ import annotations

from typing import Any, Protocol


class ProjectKnowledgeQueryPort(Protocol):
    """Project catalog, knowledge evidence, FAQ, and feature query surface."""

    async def active_project_ids(self) -> list[str]: ...
    async def active_projects_with_card(self) -> list[Any]: ...
    async def project_id_by_slug(self, slug: str, *, active_only: bool = False) -> Any: ...
    async def match_faq(
        self, emb: str, *, top_k: int = 3, project_ids: list[str] | None = None
    ) -> list[Any]: ...
    async def match_documents(
        self,
        emb: str,
        top_k: int,
        filter_json: str,
        *,
        project_ids: list[str] | None = None,
        query_text: str = "",
    ) -> list[Any]: ...
    async def list_active_projects(self) -> list[Any]:
        """Every active project as ``ProjectFeatures`` rows (the fit catalog)."""
    async def search_bus_timetable(
        self, company: str, question: str, limit: int
    ) -> list[Any]: ...

__all__ = ["ProjectKnowledgeQueryPort"]
