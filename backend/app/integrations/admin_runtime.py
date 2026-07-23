"""Concrete runtime adapters used by integration administration transports."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ZALO_BOT_WEBHOOK_URL, get_settings
from app.core.http import get_http_client
from app.core.redis import get_redis
from app.identity.domain.role import Role
from app.models.user import User


async def get_integration_http_client(name: str, *, timeout: float):
    return await get_http_client(name, timeout=timeout)


def get_integration_redis():
    return get_redis()


def get_integration_settings():
    return get_settings()


async def load_enabled_admin(db: AsyncSession, user_id):
    user = await db.get(User, user_id)
    if user is None or user.disabled or user.role != Role.admin:
        return None
    return user


__all__ = [
    "ZALO_BOT_WEBHOOK_URL",
    "get_integration_http_client",
    "get_integration_redis",
    "get_integration_settings",
    "load_enabled_admin",
]
