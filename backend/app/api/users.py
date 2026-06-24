"""User admin routes — every endpoint is require_admin-gated (spec §17)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.user import UserCreate, UserListResponse, UserOut, UserUpdate
from app.services.user_service import UserProvisioningService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    role: Role | None = None,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    svc = UserProvisioningService(db)
    rows, total = await svc.list(page=page, per_page=per_page, role=role)
    return UserListResponse(data=[UserOut.model_validate(r) for r in rows], total=total)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    svc = UserProvisioningService(db)
    try:
        user = await svc.create(body, actor_id=admin.id)
    except ValueError as exc:  # email already exists
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return UserOut.model_validate(user)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    svc = UserProvisioningService(db)
    user = await svc.get(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    svc = UserProvisioningService(db)
    try:
        user = await svc.update(user_id, body, actor_id=admin.id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return UserOut.model_validate(user)


@router.post("/{user_id}/disable", response_model=UserOut)
async def disable_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bạn không thể vô hiệu hóa chính mình",
        )
    return await _set_disabled(user_id=user_id, disabled=True, actor=admin, db=db)


@router.post("/{user_id}/enable", response_model=UserOut)
async def enable_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    return await _set_disabled(user_id=user_id, disabled=False, actor=admin, db=db)


async def _set_disabled(
    *, user_id: uuid.UUID, disabled: bool, actor: User, db: AsyncSession
) -> UserOut:
    svc = UserProvisioningService(db)
    try:
        user = await svc.set_disabled(user_id, disabled, actor_id=actor.id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return UserOut.model_validate(user)
