"""Framework-free Facebook OAuth state and flow types."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FacebookOAuthAdminBinding:
    admin_id: UUID
    token_version: int


@dataclass(frozen=True, slots=True)
class FacebookOAuthPage:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class FacebookOAuthFlow:
    admin: FacebookOAuthAdminBinding
    user_token: str
    pages: tuple[FacebookOAuthPage, ...]
