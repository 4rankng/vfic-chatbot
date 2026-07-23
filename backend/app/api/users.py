"""User routes — self-service /me + admin CRUD (require_admin-gated)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import get_current_user, require_admin
from app.identity.application.http import AuthenticatedUser
from app.identity.infrastructure.http import build_user_http_service
from app.schemas.user import (
    AdminPasswordReset,
    Role,
    SelfProfileUpdate,
    UserCreate,
    UserListResponse,
    UserOut,
    UserUpdate,
)
from app.shared.infrastructure.db import get_request_db

router = APIRouter(prefix="/users", tags=["users"])


# ── Self-service (any authenticated user) ─────────────────────────────────


@router.get("/me", response_model=UserOut)
async def get_me(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> UserOut:
    return await build_user_http_service(db).get_me(current=user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: SelfProfileUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> UserOut:
    svc = build_user_http_service(db)
    try:
        return await svc.update_me(current=user, body=body)
    except ValueError as exc:  # email already exists
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# ── Admin CRUD ─────────────────────────────────────────────────────────────


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    role: Role | None = None,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> UserListResponse:
    return await build_user_http_service(db).list_users(page=page, per_page=per_page, role=role)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> UserOut:
    svc = build_user_http_service(db)
    try:
        return await svc.create_user(body=body, actor_id=admin.id)
    except ValueError as exc:  # email already exists
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> UserOut:
    user = await build_user_http_service(db).get_user(user_id=user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> UserOut:
    svc = build_user_http_service(db)
    try:
        return await svc.update_user(user_id=user_id, body=body, actor_id=admin.id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{user_id}/disable", response_model=UserOut)
async def disable_user(
    user_id: uuid.UUID,
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> UserOut:
    return await _set_disabled(user_id=user_id, disabled=True, actor=admin, db=db)


@router.post("/{user_id}/enable", response_model=UserOut)
async def enable_user(
    user_id: uuid.UUID,
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> UserOut:
    return await _set_disabled(user_id=user_id, disabled=False, actor=admin, db=db)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_user_password(
    user_id: uuid.UUID,
    body: AdminPasswordReset,
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> None:
    svc = build_user_http_service(db)
    try:
        await svc.reset_password(user_id=user_id, body=body, actor_id=admin.id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> None:
    svc = build_user_http_service(db)
    try:
        await svc.delete_user(user_id=user_id, actor_id=admin.id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def _set_disabled(
    *,
    user_id: uuid.UUID,
    disabled: bool,
    actor: AuthenticatedUser,
    db: AsyncSession,
) -> UserOut:
    svc = build_user_http_service(db)
    try:
        return await svc.set_disabled(user_id=user_id, disabled=disabled, actor_id=actor.id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
