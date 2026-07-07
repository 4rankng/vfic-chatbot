"""Database-backed integration settings with encrypted secret values."""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
# OAuth-managed (scan-to-connect). The access token above is also written by the
# OAuth flow; these two only ever come from the flow (manual PUT cannot set them).
ZALO_OA_REFRESH_TOKEN = "zalo_oa_refresh_token"
ZALO_OA_ACCESS_TOKEN_EXPIRES_AT = "zalo_oa_access_token_expires_at"
MINIMAX_API_KEY = "minimax_api_key"
OPENROUTER_API_KEY = "openrouter_api_key"

ZALO_SETTING_KEYS = (
    ZALO_BOT_TOKEN,
    ZALO_BOT_WEBHOOK_SECRET,
    ZALO_OA_APP_ID,
    ZALO_OA_SECRET_KEY,
    ZALO_OA_ACCESS_TOKEN,
    ZALO_OA_REFRESH_TOKEN,
    ZALO_OA_ACCESS_TOKEN_EXPIRES_AT,
)

# Refresh an OA access token when it has less than this long to live. Tokens last
# 1h; because every outbound turn re-resolves config, refreshing here keeps every
# send on a valid token without any sender-side retry logic.
OA_REFRESH_SAFETY_MARGIN_SECONDS = 300

MINIMAX_SETTING_KEYS = (MINIMAX_API_KEY,)
OPENROUTER_SETTING_KEYS = (OPENROUTER_API_KEY,)


@dataclass(frozen=True)
class ZaloRuntimeConfig:
    bot_token: str = ""
    bot_webhook_secret: str = ""
    oa_app_id: str = ""
    oa_secret_key: str = ""
    oa_access_token: str = ""
    # OAuth-managed fields. Empty when the OA was wired up manually (no refresh).
    oa_refresh_token: str = ""
    oa_access_token_expires_at: str = ""  # ISO-8601 UTC, "" = unknown
    bot_api_base: str = ZALO_BOT_API_BASE
    oa_api_base: str = ZALO_OA_API_BASE


@dataclass(frozen=True)
class MinimaxRuntimeConfig:
    api_key: str = ""
    base_url: str = ""
    agent_model: str = ""
    safety_model: str = ""


@dataclass(frozen=True)
class OpenRouterRuntimeConfig:
    api_key: str = ""
    base_url: str = ""
    agent_model: str = ""
    safety_model: str = ""
    digest_model: str = ""
    embedding_model: str = ""
    embedding_dim: int = 3072


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
        await self._maybe_refresh_oa_token(stored)
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
            oa_refresh_token=stored.get(ZALO_OA_REFRESH_TOKEN) or "",
            oa_access_token_expires_at=stored.get(ZALO_OA_ACCESS_TOKEN_EXPIRES_AT) or "",
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
            "zalo_oa_refresh_token": {
                "configured": bool(cfg.oa_refresh_token),
                "preview": _preview(cfg.oa_refresh_token),
            },
            # Non-secret ISO expiry (None when the OA was set up manually / no OAuth).
            "zalo_oa_access_token_expires_at": cfg.oa_access_token_expires_at or None,
            # Convenience flag for the frontend: only true when the OAuth flow has
            # run (refresh token present). Manual token entry leaves it false.
            "zalo_oa_connected": bool(cfg.oa_refresh_token and cfg.oa_access_token),
            "zalo_bot_api_base": ZALO_BOT_API_BASE,
            "zalo_oa_api_base": ZALO_OA_API_BASE,
        }

    async def resolve_minimax(self) -> MinimaxRuntimeConfig:
        stored = await self._stored_values(MINIMAX_SETTING_KEYS)
        return MinimaxRuntimeConfig(
            api_key=stored.get(MINIMAX_API_KEY) or self.settings.minimax_api_key,
            base_url=self.settings.minimax_base_url,
            agent_model=self.settings.minimax_agent_model,
            safety_model=self.settings.minimax_safety_model,
        )

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
        }

    async def resolve_openrouter(self) -> OpenRouterRuntimeConfig:
        stored = await self._stored_values(OPENROUTER_SETTING_KEYS)
        return OpenRouterRuntimeConfig(
            api_key=stored.get(OPENROUTER_API_KEY) or self.settings.openrouter_api_key,
            base_url=self.settings.openrouter_base_url,
            agent_model=self.settings.openrouter_agent_model,
            safety_model=self.settings.openrouter_safety_model,
            digest_model=self.settings.openrouter_digest_model,
            embedding_model=self.settings.openrouter_embedding_model,
            embedding_dim=self.settings.embedding_dim,
        )

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

    async def _upsert(
        self,
        key: str,
        value: str,
        actor_id: uuid.UUID | None,
        *,
        secret: bool,
    ) -> None:
        """Encrypt and upsert one setting row (no commit — caller commits)."""
        encrypted = self.cipher.encrypt(value)
        row = await self.db.get(IntegrationSetting, key)
        if row is None:
            row = IntegrationSetting(
                key=key,
                encrypted_value=encrypted,
                is_secret=secret,
                updated_by=actor_id,
            )
            self.db.add(row)
        else:
            row.encrypted_value = encrypted
            row.is_secret = secret
            row.updated_by = actor_id

    async def store_oa_tokens(
        self,
        *,
        access_token: str,
        refresh_token: str,
        expires_at: str,
        actor_id: uuid.UUID | None,
    ) -> None:
        """Persist the OA token trio from the OAuth flow (connect or rotation).

        ``expires_at`` is an ISO-8601 UTC string (non-secret) so admin_view can
        surface expiry without decrypting anything.
        """
        await self._upsert(ZALO_OA_ACCESS_TOKEN, access_token, actor_id, secret=True)
        await self._upsert(ZALO_OA_REFRESH_TOKEN, refresh_token, actor_id, secret=True)
        await self._upsert(
            ZALO_OA_ACCESS_TOKEN_EXPIRES_AT, expires_at, actor_id, secret=False
        )
        await record_audit(
            self.db,
            action="zalo_oauth_connect" if actor_id else "zalo_oauth_token_refresh",
            actor_id=actor_id,
            target_type="integration_settings",
            target_id="zalo",
            payload={"expires_at": expires_at},
        )
        await self.db.commit()

    async def clear_zalo_oa_tokens(self, *, actor_id: uuid.UUID) -> None:
        """Disconnect: remove the OAuth-managed OA tokens. Leaves app_id/secret."""
        from sqlalchemy import delete

        keys = (
            ZALO_OA_ACCESS_TOKEN,
            ZALO_OA_REFRESH_TOKEN,
            ZALO_OA_ACCESS_TOKEN_EXPIRES_AT,
        )
        await self.db.execute(
            delete(IntegrationSetting).where(IntegrationSetting.key.in_(keys))
        )
        await record_audit(
            self.db,
            action="zalo_oauth_disconnect",
            actor_id=actor_id,
            target_type="integration_settings",
            target_id="zalo",
            payload={"cleared_keys": list(keys)},
        )
        await self.db.commit()

    async def _maybe_refresh_oa_token(self, stored: dict[str, str]) -> None:
        """Proactively rotate the OA access token when it is near expiry.

        OA access tokens last 1h; refresh tokens last 3 months and rotate on each
        use. Every outbound path (chatbot turns via build_deps AND recruiter-reply
        delivery via services.conversation) flows through resolve_zalo before
        constructing the sender, so refreshing here keeps every send on a valid
        token with zero sender-side retry logic.

        The rotation is persisted in an ISOLATED session so it can never commit or
        roll back the caller's in-flight transaction. Any failure is swallowed:
        ``stored`` is left untouched and the existing (near-expiry, still-valid-for
        its remaining seconds) token is used instead — a genuinely expired token
        simply fails that one send rather than corrupting state.
        """
        refresh_token = stored.get(ZALO_OA_REFRESH_TOKEN)
        expires_at_str = stored.get(ZALO_OA_ACCESS_TOKEN_EXPIRES_AT)
        if not refresh_token or not expires_at_str:
            return  # Manual setup (no OAuth) — nothing to refresh.
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
        except ValueError:
            return  # Malformed expiry — don't speculate.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if (expires_at - now).total_seconds() > OA_REFRESH_SAFETY_MARGIN_SECONDS:
            return  # Still fresh.
        app_id = stored.get(ZALO_OA_APP_ID) or self.settings.zalo_oa_app_id
        secret_key = stored.get(ZALO_OA_SECRET_KEY) or self.settings.zalo_oa_secret_key
        if not app_id or not secret_key:
            return  # Can't refresh without app credentials.
        try:
            from app.services.zalo_oa_oauth import ZaloOAOAuthClient

            token_set = await ZaloOAOAuthClient(app_id, secret_key).refresh(refresh_token)
        except Exception:  # noqa: BLE001 — refresh is best-effort, never fatal
            return
        new_expires_at = now + timedelta(
            seconds=max(token_set.expires_in - OA_REFRESH_SAFETY_MARGIN_SECONDS, 60)
        )
        iso = new_expires_at.isoformat()
        try:
            from app.core.db import async_session

            async with async_session() as session:
                # Reuse this instance's cipher so the rotation is encrypted with
                # the same key the rest of the row set uses.
                await IntegrationSettingsService(
                    session, settings=self.settings, cipher=self.cipher
                ).store_oa_tokens(
                    access_token=token_set.access_token,
                    refresh_token=token_set.refresh_token,
                    expires_at=iso,
                    actor_id=None,
                )
        except Exception:  # noqa: BLE001 — never let refresh break a chat turn
            return
        stored[ZALO_OA_ACCESS_TOKEN] = token_set.access_token
        stored[ZALO_OA_REFRESH_TOKEN] = token_set.refresh_token
        stored[ZALO_OA_ACCESS_TOKEN_EXPIRES_AT] = iso

    async def update_minimax(self, values: dict[str, str | None], *, actor_id) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in MINIMAX_SETTING_KEYS or value is None:
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
                    is_secret=True,
                    updated_by=actor_id,
                )
                self.db.add(row)
            else:
                row.encrypted_value = encrypted
                row.is_secret = True
                row.updated_by = actor_id
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
        return changed

    async def update_openrouter(
        self,
        values: dict[str, str | None],
        *,
        actor_id,
    ) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in OPENROUTER_SETTING_KEYS or value is None:
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
                    is_secret=True,
                    updated_by=actor_id,
                )
                self.db.add(row)
            else:
                row.encrypted_value = encrypted
                row.is_secret = True
                row.updated_by = actor_id
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
        return changed
