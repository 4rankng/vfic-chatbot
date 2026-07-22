"""Framework-free ports for identity authentication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, TypeVar
from uuid import UUID


class AccessTokenDecoder(Protocol):
    async def decode(self, token: str) -> Mapping[str, object]:
        """Decode an access token payload."""


class UserIdentityRecord(Protocol):
    disabled: bool
    token_version: int


UserT = TypeVar("UserT", bound=UserIdentityRecord)


class UserIdentityGateway(Protocol[UserT]):
    async def get_by_id(self, user_id: UUID) -> UserT | None:
        """Load the authenticated user object."""
