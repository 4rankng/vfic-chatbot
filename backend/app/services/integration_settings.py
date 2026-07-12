"""Database-backed integration settings with encrypted secret values."""

from __future__ import annotations

import base64
import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Iterable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import (
    EMBEDDING_DIM,
    Settings,
    ZALO_BOT_API_BASE,
    ZALO_OA_API_BASE,
    get_settings,
)
from app.core.cache import bump_cache_version
from app.core.preamble_cache import (
    NS_INTEGRATION_MINIMAX,
    NS_INTEGRATION_OPENROUTER,
    NS_INTEGRATION_ZALO,
    cached_minimax_config,
    cached_openrouter_config,
    cached_zalo_config,
)
from app.models.integration import IntegrationSetting
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

# OA OAuth token endpoint (grant_type=authorization_code | refresh_token).
# Access tokens are opaque and valid for 25 hours; refresh tokens are valid for
# three months but single-use. Refresh on demand and persist every rotated pair.
ZALO_OA_TOKEN_URL = "https://oauth.zaloapp.com/v4/oa/access_token"


ZALO_BOT_TOKEN = "zalo_bot_token"
ZALO_BOT_WEBHOOK_SECRET = "zalo_bot_webhook_secret"
ZALO_OA_APP_ID = "zalo_oa_app_id"
ZALO_OA_SECRET_KEY = "zalo_oa_secret_key"
ZALO_OA_ACCESS_TOKEN = "zalo_oa_access_token"
ZALO_OA_REFRESH_TOKEN = "zalo_oa_refresh_token"
MINIMAX_API_KEY = "minimax_api_key"
MINIMAX_ENABLE = "minimax_enable"
OPENROUTER_API_KEY = "openrouter_api_key"
OPENROUTER_ENABLE = "openrouter_enable"
OPENROUTER_AGENT_MODEL = "openrouter_agent_model"
OPENROUTER_SAFETY_MODEL = "openrouter_safety_model"
OPENROUTER_DIGEST_MODEL = "openrouter_digest_model"
LLM_DEFAULT_PROVIDER = "llm_default_provider"

ZALO_SETTING_KEYS = (
    ZALO_BOT_TOKEN,
    ZALO_BOT_WEBHOOK_SECRET,
    ZALO_OA_APP_ID,
    ZALO_OA_SECRET_KEY,
    ZALO_OA_ACCESS_TOKEN,
    ZALO_OA_REFRESH_TOKEN,
)

MINIMAX_SETTING_KEYS = (MINIMAX_API_KEY, MINIMAX_ENABLE, LLM_DEFAULT_PROVIDER)
OPENROUTER_SETTING_KEYS = (
    OPENROUTER_API_KEY,
    OPENROUTER_ENABLE,
    OPENROUTER_AGENT_MODEL,
    OPENROUTER_SAFETY_MODEL,
    OPENROUTER_DIGEST_MODEL,
    LLM_DEFAULT_PROVIDER,
)


@dataclass(frozen=True)
class ZaloRuntimeConfig:
    bot_token: str = ""
    bot_webhook_secret: str = ""
    oa_app_id: str = ""
    oa_secret_key: str = ""
    oa_access_token: str = ""
    oa_refresh_token: str = ""
    bot_api_base: str = ZALO_BOT_API_BASE
    oa_api_base: str = ZALO_OA_API_BASE


@dataclass(frozen=True)
class MinimaxRuntimeConfig:
    api_key: str = ""
    base_url: str = ""
    agent_model: str = ""
    safety_model: str = ""
    enabled: bool = True
    default_provider: str = "minimax"


@dataclass(frozen=True)
class OpenRouterRuntimeConfig:
    api_key: str = ""
    base_url: str = ""
    agent_model: str = ""
    safety_model: str = ""
    digest_model: str = ""
    embedding_model: str = ""
    embedding_dim: int = EMBEDDING_DIM
    enabled: bool = False
    default_provider: str = "minimax"


class IntegrationSettingsCipher:
    """Small AES-GCM wrapper for settings secrets.

    The DB stores opaque `v1:<base64(nonce+ciphertext)>` values. In development,
    the JWT secret is accepted as a fallback key so local setup stays light; in
    production Settings.model_post_init requires INTEGRATION_SETTINGS_ENCRYPTION_KEY.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        raw = self._settings.integration_settings_encryption_key or self._settings.jwt_secret
        self._key = hashlib.sha256(raw.encode("utf-8")).digest()

    def encrypt(self, value: str) -> str:
        nonce = os.urandom(12)
        sealed = AESGCM(self._key).encrypt(nonce, value.encode("utf-8"), None)
        return "v1:" + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt(self, stored: str) -> str:
        if not stored:
            return ""
        if not stored.startswith("v1:"):
            # Allows manual dev rows / future imports to fail soft rather than
            # bricking runtime resolution.
            return stored
        payload = base64.urlsafe_b64decode(stored[3:].encode("ascii"))
        nonce, sealed = payload[:12], payload[12:]
        return AESGCM(self._key).decrypt(nonce, sealed, None).decode("utf-8")


def _preview(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _bool_value(value: str | None, fallback: bool) -> bool:
    if value is None:
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _provider_value(value: str | None, fallback: str) -> str:
    candidate = (value or fallback or "minimax").strip().lower()
    return candidate if candidate in {"minimax", "openrouter"} else "minimax"


class IntegrationSettingsService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        settings: Settings | None = None,
        cipher: IntegrationSettingsCipher | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.cipher = cipher or IntegrationSettingsCipher(self.settings)

    async def _stored_values(self, keys: Iterable[str]) -> dict[str, str]:
        if not hasattr(self.db, "scalars"):
            return {}
        result = await self.db.scalars(
            select(IntegrationSetting).where(IntegrationSetting.key.in_(list(keys)))
        )
        rows = result.all() if hasattr(result, "all") else []
        if hasattr(rows, "__await__"):
            return {}
        values: dict[str, str] = {}
        for row in rows:
            values[row.key] = self.cipher.decrypt(row.encrypted_value)
        return values

    async def resolve_zalo(self) -> ZaloRuntimeConfig:
        async def _load() -> dict:
            stored = await self._stored_values(ZALO_SETTING_KEYS)
            return ZaloRuntimeConfig(
                bot_token=stored.get(ZALO_BOT_TOKEN) or self.settings.zalo_bot_token,
                bot_webhook_secret=(
                    stored.get(ZALO_BOT_WEBHOOK_SECRET) or self.settings.zalo_bot_webhook_secret
                ),
                oa_app_id=stored.get(ZALO_OA_APP_ID) or self.settings.zalo_oa_app_id,
                oa_secret_key=stored.get(ZALO_OA_SECRET_KEY) or self.settings.zalo_oa_secret_key,
                oa_access_token=(
                    stored.get(ZALO_OA_ACCESS_TOKEN) or self.settings.zalo_oa_access_token
                ),
                oa_refresh_token=(
                    stored.get(ZALO_OA_REFRESH_TOKEN) or self.settings.zalo_oa_refresh_token
                ),
            ).__dict__

        cached = await cached_zalo_config(_load)
        return ZaloRuntimeConfig(**cached)

    async def admin_view(self) -> dict:
        # Local import so tests can monkeypatch read_oa_signature_health.
        from app.services.zalo_oa_health import read_oa_signature_health

        cfg = await self.resolve_zalo()
        signature_health = await read_oa_signature_health()
        return {
            "zalo_bot_token": {
                "configured": bool(cfg.bot_token),
                "preview": _preview(cfg.bot_token),
            },
            "zalo_bot_webhook_secret": {
                "configured": bool(cfg.bot_webhook_secret),
                "preview": _preview(cfg.bot_webhook_secret),
            },
            "zalo_oa_app_id": {
                "configured": bool(cfg.oa_app_id),
                "value": cfg.oa_app_id or None,
            },
            "zalo_oa_secret_key": {
                "configured": bool(cfg.oa_secret_key),
                "preview": _preview(cfg.oa_secret_key),
            },
            "zalo_oa_access_token": {
                "configured": bool(cfg.oa_access_token),
                "preview": _preview(cfg.oa_access_token),
            },
            "zalo_oa_refresh_token": {
                "configured": bool(cfg.oa_refresh_token),
                "preview": _preview(cfg.oa_refresh_token),
            },
            "zalo_bot_api_base": ZALO_BOT_API_BASE,
            "zalo_oa_api_base": ZALO_OA_API_BASE,
            "zalo_oa_webhook_signature": signature_health,
        }

    async def resolve_minimax(self) -> MinimaxRuntimeConfig:
        async def _load() -> dict:
            stored = await self._stored_values(MINIMAX_SETTING_KEYS)
            return MinimaxRuntimeConfig(
                api_key=stored.get(MINIMAX_API_KEY) or self.settings.minimax_api_key,
                base_url=self.settings.minimax_base_url,
                agent_model=self.settings.minimax_agent_model,
                safety_model=self.settings.minimax_safety_model,
                enabled=_bool_value(stored.get(MINIMAX_ENABLE), self.settings.minimax_enable),
                default_provider=_provider_value(
                    stored.get(LLM_DEFAULT_PROVIDER),
                    getattr(self.settings, "llm_default_provider", "minimax"),
                ),
            ).__dict__

        cached = await cached_minimax_config(_load)
        return MinimaxRuntimeConfig(**cached)

    async def admin_minimax_view(self) -> dict:
        cfg = await self.resolve_minimax()
        return {
            "minimax_api_key": {
                "configured": bool(cfg.api_key),
                "preview": _preview(cfg.api_key),
            },
            "minimax_base_url": cfg.base_url,
            "minimax_agent_model": cfg.agent_model,
            "minimax_safety_model": cfg.safety_model,
            "minimax_enable": cfg.enabled,
            "llm_default_provider": cfg.default_provider,
        }

    async def resolve_openrouter(self) -> OpenRouterRuntimeConfig:
        async def _load() -> dict:
            stored = await self._stored_values(OPENROUTER_SETTING_KEYS)
            return OpenRouterRuntimeConfig(
                api_key=stored.get(OPENROUTER_API_KEY) or self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url,
                agent_model=stored.get(OPENROUTER_AGENT_MODEL)
                or self.settings.openrouter_agent_model,
                safety_model=(
                    stored.get(OPENROUTER_SAFETY_MODEL) or self.settings.openrouter_safety_model
                ),
                digest_model=(
                    stored.get(OPENROUTER_DIGEST_MODEL) or self.settings.openrouter_digest_model
                ),
                embedding_model=self.settings.openrouter_embedding_model,
                embedding_dim=self.settings.embedding_dim,
                enabled=_bool_value(stored.get(OPENROUTER_ENABLE), self.settings.openrouter_enable),
                default_provider=_provider_value(
                    stored.get(LLM_DEFAULT_PROVIDER),
                    getattr(self.settings, "llm_default_provider", "minimax"),
                ),
            ).__dict__

        cached = await cached_openrouter_config(_load)
        return OpenRouterRuntimeConfig(**cached)

    async def admin_openrouter_view(self) -> dict:
        cfg = await self.resolve_openrouter()
        return {
            "openrouter_api_key": {
                "configured": bool(cfg.api_key),
                "preview": _preview(cfg.api_key),
            },
            "openrouter_base_url": cfg.base_url,
            "openrouter_agent_model": cfg.agent_model,
            "openrouter_safety_model": cfg.safety_model,
            "openrouter_digest_model": cfg.digest_model,
            "openrouter_embedding_model": cfg.embedding_model,
            "openrouter_embedding_dim": cfg.embedding_dim,
            "openrouter_enable": cfg.enabled,
            "llm_default_provider": cfg.default_provider,
        }

    async def _write_setting(
        self,
        key: str,
        value: str,
        *,
        actor_id=None,
        is_secret: bool,
    ) -> bool:
        cleaned = value.strip()
        if not cleaned:
            return False
        stored_value = self.cipher.encrypt(cleaned) if is_secret else cleaned
        row = await self.db.get(IntegrationSetting, key)
        if row is None:
            row = IntegrationSetting(
                key=key,
                encrypted_value=stored_value,
                is_secret=is_secret,
                updated_by=actor_id,
            )
            self.db.add(row)
        else:
            row.encrypted_value = stored_value
            row.is_secret = is_secret
            row.updated_by = actor_id
        return True

    async def _write_secret(self, key: str, value: str | None, *, actor_id=None) -> bool:
        """Encrypt + upsert one Zalo integration row. Returns True if stored.

        Only stages the write; the caller commits (and records audit) so multi-key
        updates and token refresh can batch their persistence.
        """
        if key not in ZALO_SETTING_KEYS or value is None:
            return False
        cleaned = value.strip()
        if not cleaned:
            return False
        encrypted = self.cipher.encrypt(cleaned)
        row = await self.db.get(IntegrationSetting, key)
        if row is None:
            row = IntegrationSetting(
                key=key,
                encrypted_value=encrypted,
                is_secret=key != ZALO_OA_APP_ID,
                updated_by=actor_id,
            )
            self.db.add(row)
        else:
            row.encrypted_value = encrypted
            row.is_secret = key != ZALO_OA_APP_ID
            row.updated_by = actor_id
        return True

    async def update_zalo(self, values: dict[str, str | None], *, actor_id) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if value is None:
                continue
            if await self._write_secret(key, value, actor_id=actor_id):
                changed.append(key)

        if changed:
            await record_audit(
                self.db,
                action="update_zalo_integration_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="zalo",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
            await bump_cache_version(NS_INTEGRATION_ZALO)
        return changed

    async def refresh_oa_access_token(self) -> str | None:
        """Refresh the OA access_token from the stored refresh_token.

        Called lazily by ``ZaloOASender`` when a send reports the token invalid.
        A Redis ``SET NX EX`` lock prevents RQ workers from refreshing in
        parallel; losers re-read whatever token the winner just stored. Returns
        the new access_token, or ``None`` on any failure — the caller then
        surfaces the original send error.
        """
        import httpx

        from app.core.redis import get_redis

        cfg = await self.resolve_zalo()
        if not cfg.oa_refresh_token:
            return None

        redis = get_redis()
        lock_key = "zalo:oa:token:refresh"
        try:
            acquired = await redis.set(lock_key, "1", nx=True, ex=30)
        except Exception:  # noqa: BLE001
            logger.warning("zalo OA token refresh lock unavailable", exc_info=True)
            return None
        if not acquired:
            # Another worker owns the single-use refresh token. Wait briefly for
            # it to persist the rotated pair, reading Postgres directly so the
            # integration cache cannot hand back our stale access token.
            for _ in range(20):
                await asyncio.sleep(0.1)
                stored = await self._stored_values((ZALO_OA_ACCESS_TOKEN,))
                refreshed = stored.get(ZALO_OA_ACCESS_TOKEN)
                if refreshed and refreshed != cfg.oa_access_token:
                    return refreshed
            return None

        try:
            headers = {"secret_key": cfg.oa_secret_key} if cfg.oa_secret_key else {}
            body = {
                "grant_type": "refresh_token",
                "refresh_token": cfg.oa_refresh_token,
                "app_id": cfg.oa_app_id,
            }
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.zalo_bot_request_timeout
                ) as client:
                    resp = await client.post(ZALO_OA_TOKEN_URL, data=body, headers=headers)
                data = resp.json()
            except Exception:  # noqa: BLE001
                logger.warning("zalo OA token refresh transport error", exc_info=True)
                return None
            if not isinstance(data, dict) or not data.get("access_token"):
                return None

            new_access = str(data["access_token"])
            await self._write_secret(ZALO_OA_ACCESS_TOKEN, new_access)
            if data.get("refresh_token"):
                await self._write_secret(ZALO_OA_REFRESH_TOKEN, str(data["refresh_token"]))
            # Persist the rotated credential pair before nonessential audit/cache
            # work. Zalo refresh tokens are single-use; losing the new token due
            # to an audit failure would require manual re-authorization.
            await self.db.commit()
            try:
                await record_audit(
                    self.db,
                    action="refresh_zalo_oa_token",
                    actor_id=None,
                    target_type="integration_settings",
                    target_id="zalo",
                    payload={"rotated_refresh_token": bool(data.get("refresh_token"))},
                )
                await self.db.commit()
            except Exception:  # noqa: BLE001
                logger.warning("zalo OA token refresh audit failed", exc_info=True)
            try:
                await bump_cache_version(NS_INTEGRATION_ZALO)
            except Exception:  # noqa: BLE001
                logger.warning("zalo OA token refresh cache invalidation failed", exc_info=True)
            return new_access
        finally:
            try:
                await redis.delete(lock_key)
            except Exception:  # noqa: BLE001
                logger.warning("zalo OA token refresh lock cleanup failed", exc_info=True)

    async def update_minimax(
        self,
        values: dict[str, str | bool | None],
        *,
        actor_id,
    ) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in MINIMAX_SETTING_KEYS or value is None:
                continue
            if await self._write_setting(
                key,
                str(value),
                actor_id=actor_id,
                is_secret=key == MINIMAX_API_KEY,
            ):
                changed.append(key)

        if changed:
            await record_audit(
                self.db,
                action="update_minimax_integration_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="minimax",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
            await bump_cache_version(NS_INTEGRATION_MINIMAX)
        return changed

    async def update_openrouter(
        self,
        values: dict[str, str | bool | None],
        *,
        actor_id,
    ) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in OPENROUTER_SETTING_KEYS or value is None:
                continue
            if await self._write_setting(
                key,
                str(value),
                actor_id=actor_id,
                is_secret=key == OPENROUTER_API_KEY,
            ):
                changed.append(key)

        if changed:
            await record_audit(
                self.db,
                action="update_openrouter_integration_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="openrouter",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
            await bump_cache_version(NS_INTEGRATION_OPENROUTER)
        return changed
