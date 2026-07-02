"""Database-backed integration settings with encrypted secret values."""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Iterable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, ZALO_BOT_API_BASE, ZALO_OA_API_BASE, get_settings
from app.models.integration import IntegrationSetting
from app.services.audit_service import record_audit

ZALO_BOT_TOKEN = "zalo_bot_token"
ZALO_BOT_WEBHOOK_SECRET = "zalo_bot_webhook_secret"
ZALO_OA_APP_ID = "zalo_oa_app_id"
ZALO_OA_SECRET_KEY = "zalo_oa_secret_key"
ZALO_OA_ACCESS_TOKEN = "zalo_oa_access_token"

ZALO_SETTING_KEYS = (
    ZALO_BOT_TOKEN,
    ZALO_BOT_WEBHOOK_SECRET,
    ZALO_OA_APP_ID,
    ZALO_OA_SECRET_KEY,
    ZALO_OA_ACCESS_TOKEN,
)


@dataclass(frozen=True)
class ZaloRuntimeConfig:
    bot_token: str = ""
    bot_webhook_secret: str = ""
    oa_app_id: str = ""
    oa_secret_key: str = ""
    oa_access_token: str = ""
    bot_api_base: str = ZALO_BOT_API_BASE
    oa_api_base: str = ZALO_OA_API_BASE


class IntegrationSettingsCipher:
    """Small AES-GCM wrapper for settings secrets.

    The DB stores opaque `v1:<base64(nonce+ciphertext)>` values. In development,
    the JWT secret is accepted as a fallback key so local setup stays light; in
    production Settings.model_post_init requires INTEGRATION_SETTINGS_ENCRYPTION_KEY.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        raw = (
            self._settings.integration_settings_encryption_key
            or self._settings.jwt_secret
        )
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
        stored = await self._stored_values(ZALO_SETTING_KEYS)
        return ZaloRuntimeConfig(
            bot_token=stored.get(ZALO_BOT_TOKEN) or self.settings.zalo_bot_token,
            bot_webhook_secret=(
                stored.get(ZALO_BOT_WEBHOOK_SECRET)
                or self.settings.zalo_bot_webhook_secret
            ),
            oa_app_id=stored.get(ZALO_OA_APP_ID) or self.settings.zalo_oa_app_id,
            oa_secret_key=stored.get(ZALO_OA_SECRET_KEY) or self.settings.zalo_oa_secret_key,
            oa_access_token=(
                stored.get(ZALO_OA_ACCESS_TOKEN)
                or self.settings.zalo_oa_access_token
            ),
        )

    async def admin_view(self) -> dict:
        cfg = await self.resolve_zalo()
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
            "zalo_bot_api_base": ZALO_BOT_API_BASE,
            "zalo_oa_api_base": ZALO_OA_API_BASE,
        }

    async def update_zalo(self, values: dict[str, str | None], *, actor_id) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in ZALO_SETTING_KEYS or value is None:
                continue
            cleaned = value.strip()
            if not cleaned:
                continue
            row = await self.db.get(IntegrationSetting, key)
            encrypted = self.cipher.encrypt(cleaned)
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
        return changed
