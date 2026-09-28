"""Transport-neutral identity principals and application errors."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol
from app.identity.domain.role import Role


class AuthenticatedUser(Protocol):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
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
