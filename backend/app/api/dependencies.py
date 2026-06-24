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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_CRED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
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


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user


def require_recruiter(user: User = Depends(get_current_user)) -> User:
    """Admins satisfy recruiter-gated routes too."""
    if user.role not in (Role.admin, Role.recruiter):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="recruiter only")
    return user
