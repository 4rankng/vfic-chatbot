"""FastAPI installation and capability dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.domain.errors import ResourceNotFoundError
from app.access.infrastructure.installation import build_installation_access_policy
from app.api.auth_dependencies import get_current_user
from app.capabilities.registry import get_capability_registry
from app.identity.infrastructure.authentication import get_identity_db


def _validate_capability_id(capability_id: str) -> str:
    registry = get_capability_registry()
    known = {item.capability_id for item in registry.capabilities()}
    if capability_id not in known:
        raise ValueError(f"unknown capability dependency: {capability_id}")
    return capability_id


async def get_active_installation(
    _user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_identity_db),
) -> Any:
    return await build_installation_access_policy(db).require_active()


def require_capability(capability_id: str):
    capability_id = _validate_capability_id(capability_id)

    async def dependency(
        _user: Any = Depends(get_current_user),
        db: AsyncSession = Depends(get_identity_db),
    ) -> Any:
        try:
            return await build_installation_access_policy(db).require_capability(capability_id)
        except ResourceNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc

    dependency.__name__ = f"require_capability_{capability_id.replace('.', '_')}"
    return dependency


def require_capability_or_legacy(capability_id: str):
    capability_id = _validate_capability_id(capability_id)

    async def dependency(
        _user: Any = Depends(get_current_user),
        db: AsyncSession = Depends(get_identity_db),
    ) -> Any | None:
        try:
            return await build_installation_access_policy(db).require_capability_or_legacy(
                capability_id
            )
        except ResourceNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc

    dependency.__name__ = f"require_capability_or_legacy_{capability_id.replace('.', '_')}"
    return dependency
