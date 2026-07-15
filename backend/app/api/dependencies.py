"""FastAPI auth dependencies.

Authorization is enforced here (replaces Supabase RLS + is_vfic_staff/admin helpers).
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import decode_token
from app.models.user import Role, User
from app.services.installation.service import ActiveInstallation, InstallationService
from app.capabilities.registry import get_capability_registry

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_CRED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_user_from_token(token: str, db: AsyncSession) -> User:
    """Shared access-token verification used by every authed entry point:
    decode -> type=access -> user lookup -> disabled + token_version check.

    Raises 401 (_CRED) on any failure. Both the Bearer-header path
    (get_current_user) and the SSE ?token= path (realtime._user_from_request)
    route through here so the verification logic cannot drift between them.
    """
    try:
        payload = await decode_token(token)
        if payload.get("type") != "access":
            raise _CRED
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError):
        raise _CRED

    user = await db.get(User, user_id)
    if user is None or user.disabled:
        raise _CRED
    # Reject access tokens superseded by a password change (ver mismatch).
    if payload.get("ver", 0) != user.token_version:
        raise _CRED
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    return await get_user_from_token(token, db)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user


def require_recruiter(user: User = Depends(get_current_user)) -> User:
    """Admins satisfy recruiter-gated routes too."""
    if user.role not in (Role.admin, Role.recruiter):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="recruiter only")
    return user


async def get_active_installation(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActiveInstallation:
    """Resolve runtime authority only after authentication has succeeded."""
    return await InstallationService(db).require_active()


def require_capability(capability_id: str):
    registry = get_capability_registry()
    if capability_id not in {item.capability_id for item in registry.capabilities()}:
        raise ValueError(f"unknown capability dependency: {capability_id}")

    async def dependency(
        active: ActiveInstallation = Depends(get_active_installation),
    ) -> ActiveInstallation:
        if capability_id not in active.revision.capability_ids:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
        return active

    dependency.__name__ = f"require_capability_{capability_id.replace('.', '_')}"
    return dependency


def get_embedder():
    """DI provider for the configured embedder.

    Centralises ``app.graph.clients.build_embedder`` construction so routes (and the
    services they call) depend on this provider instead of reaching up into the graph
    layer. Imported lazily so langchain/google deps stay out of the web-process import
    path, matching the previous in-handler lazy import.
    """
    from app.graph.clients import build_embedder

    return build_embedder()
