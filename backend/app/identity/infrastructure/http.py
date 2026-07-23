"""HTTP service adapters for identity-backed API routes."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.identity.application.http import (
    AuthHttpService,
    AuthenticatedUser,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    InvalidRefreshTokenError,
    PasswordResetRequestError,
    UserHttpService,
)
from app.identity.domain.role import Role
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, TokenResponse
from app.schemas.user import (
    AdminPasswordReset,
    SelfProfileUpdate,
    UserCreate,
    UserListResponse,
    UserOut,
    UserUpdate,
)
from app.services.audit_service import record_audit
from app.services.auth_service import authenticate
from app.services.password_reset_service import PasswordResetError, PasswordResetService
from app.services.user_service import UserProvisioningService


class SqlAlchemyAuthHttpService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._settings = get_settings()

    async def _tokens_for(self, user: User) -> TokenResponse:
        return TokenResponse(
            access_token=await create_access_token(str(user.id), ver=user.token_version),
            refresh_token=await create_refresh_token(str(user.id), ver=user.token_version),
            token_type="bearer",
            expires_in=self._settings.access_token_expire_minutes * 60,
        )

    async def login(self, *, email: str, password: str) -> TokenResponse:
        user = await authenticate(self._db, email, password)
        if user is None:
            raise InvalidCredentialsError
        return await self._tokens_for(user)

    async def forgot_password(self, *, email: str) -> None:
        await PasswordResetService(self._db).request_reset(email)

    async def reset_password(self, *, email: str, otp: str, new_password: str) -> None:
        try:
            await PasswordResetService(self._db).reset_password(
                email=email,
                otp=otp,
                new_password=new_password,
            )
        except PasswordResetError as exc:
            raise PasswordResetRequestError(str(exc)) from exc

    async def refresh(self, *, refresh_token: str) -> TokenResponse:
        try:
            payload = await decode_token(refresh_token)
        except Exception as exc:  # noqa: BLE001 - invalid token details collapse upstream
            raise InvalidRefreshTokenError from exc
        if payload.get("type") != "refresh":
            raise InvalidRefreshTokenError
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise InvalidRefreshTokenError
        try:
            user_id = uuid.UUID(subject)
        except ValueError as exc:
            raise InvalidRefreshTokenError from exc

        user = await self._db.get(User, user_id)
        if user is None or user.disabled:
            raise InvalidRefreshTokenError
        if payload.get("ver", 0) != user.token_version:
            raise InvalidRefreshTokenError
        return await self._tokens_for(user)

    async def me(self, *, current: AuthenticatedUser) -> UserOut:
        return UserOut.model_validate(current)

    async def change_password(
        self,
        *,
        current: AuthenticatedUser,
        body: ChangePasswordRequest,
    ) -> None:
        if not await verify_password(body.current_password, current.password_hash):
            raise InvalidCurrentPasswordError
        current.password_hash = await hash_password(body.new_password)
        current.token_version += 1
        await record_audit(
            self._db,
            action="change_password",
            actor_id=current.id,
            target_type="user",
            target_id=str(current.id),
        )
        await self._db.commit()


class SqlAlchemyUserHttpService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._svc = UserProvisioningService(db)

    async def get_me(self, *, current: AuthenticatedUser) -> UserOut:
        await self._db.refresh(current)
        return UserOut.model_validate(current)

    async def update_me(
        self,
        *,
        current: AuthenticatedUser,
        body: SelfProfileUpdate,
    ) -> UserOut:
        updated = await self._svc.update(current.id, body, actor_id=current.id)
        return UserOut.model_validate(updated)

    async def list_users(
        self,
        *,
        page: int,
        per_page: int,
        role: Role | None,
    ) -> UserListResponse:
        rows, total = await self._svc.list(page=page, per_page=per_page, role=role)
        return UserListResponse(data=[UserOut.model_validate(row) for row in rows], total=total)

    async def create_user(self, *, body: UserCreate, actor_id: uuid.UUID) -> UserOut:
        return UserOut.model_validate(await self._svc.create(body, actor_id=actor_id))

    async def get_user(self, *, user_id: uuid.UUID) -> UserOut | None:
        user = await self._svc.get(user_id)
        return None if user is None else UserOut.model_validate(user)

    async def update_user(
        self,
        *,
        user_id: uuid.UUID,
        body: UserUpdate,
        actor_id: uuid.UUID,
    ) -> UserOut:
        return UserOut.model_validate(await self._svc.update(user_id, body, actor_id=actor_id))

    async def set_disabled(
        self,
        *,
        user_id: uuid.UUID,
        disabled: bool,
        actor_id: uuid.UUID,
    ) -> UserOut:
        user = await self._svc.set_disabled(user_id, disabled, actor_id=actor_id)
        return UserOut.model_validate(user)

    async def reset_password(
        self,
        *,
        user_id: uuid.UUID,
        body: AdminPasswordReset,
        actor_id: uuid.UUID,
    ) -> None:
        await self._svc.reset_password(user_id, body.password, actor_id=actor_id)

    async def delete_user(self, *, user_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        await self._svc.delete(user_id, actor_id=actor_id)


def build_auth_http_service(db: AsyncSession) -> AuthHttpService:
    return SqlAlchemyAuthHttpService(db)


def build_user_http_service(db: AsyncSession) -> UserHttpService:
    return SqlAlchemyUserHttpService(db)


__all__ = [
    "SqlAlchemyAuthHttpService",
    "SqlAlchemyUserHttpService",
    "build_auth_http_service",
    "build_user_http_service",
]
