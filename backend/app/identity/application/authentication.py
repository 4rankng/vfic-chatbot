"""Framework-free access-token authentication."""

from __future__ import annotations

from typing import Generic
from uuid import UUID

from app.identity.application.ports import AccessTokenDecoder, UserIdentityGateway, UserT
from app.identity.domain.errors import AuthenticationError


class AccessTokenAuthenticator(Generic[UserT]):
    def __init__(
        self,
        *,
        decoder: AccessTokenDecoder,
        users: UserIdentityGateway[UserT],
    ) -> None:
        self._decoder = decoder
        self._users = users

    async def authenticate(self, token: str) -> UserT:
        try:
            payload = await self._decoder.decode(token)
        except Exception as exc:  # noqa: BLE001 - auth failures collapse to one credential error
            raise AuthenticationError from exc

        if payload.get("type") != "access":
            raise AuthenticationError

        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise AuthenticationError
        try:
            user_id = UUID(subject)
        except ValueError as exc:
            raise AuthenticationError from exc

        user = await self._users.get_by_id(user_id)
        if user is None or user.disabled:
            raise AuthenticationError
        if payload.get("ver", 0) != user.token_version:
            raise AuthenticationError
        return user
