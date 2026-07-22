"""FastAPI auth dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.application.roles import require_admin_access, require_recruiter_access
from app.access.domain.errors import AccessDeniedError
from app.identity.domain.errors import AuthenticationError
from app.identity.infrastructure.authentication import (
    build_access_token_authenticator,
    get_identity_db,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_CRED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_user_from_token(token: str, db: AsyncSession) -> Any:
    try:
        return await build_access_token_authenticator(db).authenticate(token)
    except AuthenticationError as exc:
        raise _CRED from exc


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_identity_db),
) -> Any:
    return await get_user_from_token(token, db)


def require_admin(user: Any = Depends(get_current_user)) -> Any:
    try:
        return require_admin_access(user)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc


def require_recruiter(user: Any = Depends(get_current_user)) -> Any:
    try:
        return require_recruiter_access(user)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail) from exc
