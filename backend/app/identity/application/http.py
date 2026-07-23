"""HTTP-facing identity contracts for auth and user transports."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from app.identity.domain.role import Role
from app.schemas.auth import ChangePasswordRequest, TokenResponse
from app.schemas.user import (
    AdminPasswordReset,
    SelfProfileUpdate,
    UserCreate,
    UserListResponse,
    UserOut,
    UserUpdate,
)


class AuthenticatedUser(Protocol):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: object
    disabled: bool
    token_version: int
    password_hash: str
    created_at: datetime
    updated_at: datetime


class InvalidCredentialsError(Exception):
    detail = "Email hoặc mật khẩu không đúng"


class InvalidRefreshTokenError(Exception):
    detail = "Invalid refresh token"


class InvalidCurrentPasswordError(Exception):
    detail = "Mật khẩu hiện tại không đúng"


class PasswordResetRequestError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class AuthHttpService(Protocol):
    async def login(self, *, email: str, password: str) -> TokenResponse: ...

    async def forgot_password(self, *, email: str) -> None: ...

    async def reset_password(self, *, email: str, otp: str, new_password: str) -> None: ...

    async def refresh(self, *, refresh_token: str) -> TokenResponse: ...

    async def me(self, *, current: AuthenticatedUser) -> UserOut: ...

    async def change_password(
        self,
        *,
        current: AuthenticatedUser,
        body: ChangePasswordRequest,
    ) -> None: ...


class UserHttpService(Protocol):
    async def get_me(self, *, current: AuthenticatedUser) -> UserOut: ...

    async def update_me(
        self,
        *,
        current: AuthenticatedUser,
        body: SelfProfileUpdate,
    ) -> UserOut: ...

    async def list_users(
        self,
        *,
        page: int,
        per_page: int,
        role: Role | None,
    ) -> UserListResponse: ...

    async def create_user(self, *, body: UserCreate, actor_id: uuid.UUID) -> UserOut: ...

    async def get_user(self, *, user_id: uuid.UUID) -> UserOut | None: ...

    async def update_user(
        self,
        *,
        user_id: uuid.UUID,
        body: UserUpdate,
        actor_id: uuid.UUID,
    ) -> UserOut: ...

    async def set_disabled(
        self,
        *,
        user_id: uuid.UUID,
        disabled: bool,
        actor_id: uuid.UUID,
    ) -> UserOut: ...

    async def reset_password(
        self,
        *,
        user_id: uuid.UUID,
        body: AdminPasswordReset,
        actor_id: uuid.UUID,
    ) -> None: ...

    async def delete_user(self, *, user_id: uuid.UUID, actor_id: uuid.UUID) -> None: ...
