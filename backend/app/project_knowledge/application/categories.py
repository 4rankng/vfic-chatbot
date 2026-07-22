"""Application entry points for the project category lifecycle."""

from __future__ import annotations

from typing import Any, Protocol


class CategoryLifecyclePort(Protocol):
    async def list_catalog(self, project_id: object) -> Any: ...

    async def get_active_source(self, project_id: object, category_key: object) -> Any: ...

    async def stage_replacement(
        self,
        *,
        project_id: object,
        category_key: object,
        filename: str,
        source_yaml: str,
        actor: object,
    ) -> Any: ...

    async def activate_revision(
        self,
        revision_id: object,
        embedder: object,
        *,
        claim_token: object | None = None,
    ) -> Any: ...

    async def clear(
        self,
        *,
        project_id: object,
        category_key: object,
        actor: object,
    ) -> Any: ...

    async def cutover_category_authority(
        self,
        *,
        project_id: object,
        actor: object,
    ) -> Any: ...

    async def rollback_category_authority(
        self,
        *,
        project_id: object,
        actor: object,
    ) -> Any: ...


class CategoryUseCases:
    """Keep transports and workers independent of the SQLAlchemy compatibility service."""

    def __init__(self, port: CategoryLifecyclePort) -> None:
        self._port = port

    async def list_catalog(self, project_id: object) -> Any:
        return await self._port.list_catalog(project_id)

    async def get_active_source(self, project_id: object, category_key: object) -> Any:
        return await self._port.get_active_source(project_id, category_key)

    async def stage_replacement(
        self,
        *,
        project_id: object,
        category_key: object,
        filename: str,
        source_yaml: str,
        actor: object,
    ) -> Any:
        return await self._port.stage_replacement(
            project_id=project_id,
            category_key=category_key,
            filename=filename,
            source_yaml=source_yaml,
            actor=actor,
        )

    async def activate_revision(
        self,
        revision_id: object,
        embedder: object,
        *,
        claim_token: object | None = None,
    ) -> Any:
        return await self._port.activate_revision(
            revision_id,
            embedder,
            claim_token=claim_token,
        )

    async def clear(
        self,
        *,
        project_id: object,
        category_key: object,
        actor: object,
    ) -> Any:
        return await self._port.clear(
            project_id=project_id,
            category_key=category_key,
            actor=actor,
        )

    async def cutover_category_authority(
        self,
        *,
        project_id: object,
        actor: object,
    ) -> Any:
        return await self._port.cutover_category_authority(
            project_id=project_id,
            actor=actor,
        )

    async def rollback_category_authority(
        self,
        *,
        project_id: object,
        actor: object,
    ) -> Any:
        return await self._port.rollback_category_authority(
            project_id=project_id,
            actor=actor,
        )


__all__ = ["CategoryLifecyclePort", "CategoryUseCases"]
