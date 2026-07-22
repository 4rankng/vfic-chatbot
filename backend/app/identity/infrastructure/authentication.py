"""Infrastructure adapters for identity authentication."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.identity.application.authentication import AccessTokenAuthenticator
from app.models.user import User


class JwtAccessTokenDecoder:
    async def decode(self, token: str) -> Mapping[str, object]:
        return await decode_token(token)


class SqlAlchemyUserIdentityGateway:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._db.get(User, user_id)


def build_access_token_authenticator(db: AsyncSession) -> AccessTokenAuthenticator[User]:
    return AccessTokenAuthenticator(
        decoder=JwtAccessTokenDecoder(),
        users=SqlAlchemyUserIdentityGateway(db),
    )
