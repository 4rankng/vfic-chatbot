"""Database-backed integration settings with encrypted secret values."""

from __future__ import annotations

import base64
import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Iterable

from cryptography.exceptions import InvalidTag
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
    NS_INTEGRATION_FACEBOOK,
    NS_INTEGRATION_MINIMAX,
    NS_INTEGRATION_OPENROUTER,
    NS_INTEGRATION_ZALO,
    cached_facebook_oauth_config,
    cached_minimax_config,
    cached_openrouter_config,
    cached_zalo_config,
    evict_local_namespace,
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

# Facebook Messenger (Phase 4). Page tokens are stored per-Page under
# "facebook_page_token:<page_id>" with context-bound ciphertext (the page_id
# is the AEAD associated data, so a row moved between Pages fails to decrypt).
FB_APP_ID = "facebook_app_id"
FB_APP_SECRET = "facebook_app_secret"
FB_LOGIN_CONFIG_ID = "facebook_login_config_id"
FB_WEBHOOK_VERIFY_TOKEN = "facebook_webhook_verify_token"
FB_PAGE_TOKEN_PREFIX = "facebook_page_token:"  # + page_id → encrypted Page token
# Per-Page tokens are dynamic (keyed by page_id) and listed separately.
FB_SETTING_KEYS = (FB_APP_ID, FB_APP_SECRET, FB_LOGIN_CONFIG_ID, FB_WEBHOOK_VERIFY_TOKEN)
# Secrets are AES-GCM encrypted at rest; app_id and login_config_id are not
# sensitive (they appear in the browser OAuth URL) and stored as plaintext.
FB_SECRET_KEYS = (FB_APP_SECRET, FB_WEBHOOK_VERIFY_TOKEN)

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
class FacebookRuntimeConfig:
    """Resolved Facebook/Meta credentials for one active Page.

    ``page_access_token`` is the decrypted Graph API Page token; it is resolved
    server-side only and never serialized into API responses, logs, or queue
    payloads. ``app_secret`` is the Meta App secret used for webhook HMAC and
    API calls. All fields are deployment-owned (config) or DB-resolved.
    """

    app_id: str = ""
    app_secret: str = ""
    page_id: str = ""
    page_access_token: str = ""
    verify_token: str = ""
    graph_api_version: str = "v25.0"
    graph_api_base: str = "https://graph.facebook.com"


@dataclass(frozen=True)
class FacebookOAuthConfig:
    """Resolved Meta App credentials used to drive OAuth + webhook verification.

    These are the app-level secrets configurable via the admin UI (DB-first,
    ``Settings.meta_*`` env fallback). Unlike :class:`FacebookRuntimeConfig`,
    they are NOT bound to a specific Page — they describe the Meta App itself.
    """

    app_id: str = ""
    app_secret: str = ""
    login_config_id: str = ""
    verify_token: str = ""
    graph_api_version: str = "v25.0"
    graph_api_base: str = "https://graph.facebook.com"


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

    def encrypt_with_context(self, value: str, context: str) -> str:
        """Bind ``context`` into the AEAD associated data (Red Team #7).

        A ciphertext produced for one context (e.g. Page id ``A``) will NOT
        decrypt under another (Page id ``B``) — the GCM tag fails. This blocks
        a token row moved between Pages from decrypting successfully. Stored
        under a ``v2:`` prefix so legacy ``v1:`` rows decrypt unchanged via
        :meth:`decrypt_with_context`'s fallback.
        """
        nonce = os.urandom(12)
        aad = context.encode("utf-8")
        sealed = AESGCM(self._key).encrypt(nonce, value.encode("utf-8"), aad)
        return "v2:" + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt_with_context(self, stored: str, context: str) -> str:
        """Inverse of :meth:`encrypt_with_context`.

        ``v2:`` rows require the matching context; ``v1:`` rows (no context
        binding) decrypt via the legacy path for the rolling window. A ``v2:``
        row with the wrong context raises ``InvalidTag`` (the caller surfaces a
        reconnect-required error rather than accepting a swapped token).
        """
        if not stored:
            return ""
        if not stored.startswith("v2:"):
            return self.decrypt(stored)
        payload = base64.urlsafe_b64decode(stored[3:].encode("ascii"))
        nonce, sealed = payload[:12], payload[12:]
        aad = context.encode("utf-8")
        return AESGCM(self._key).decrypt(nonce, sealed, aad).decode("utf-8")


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
            try:
                values[row.key] = self.cipher.decrypt(row.encrypted_value)
            except InvalidTag:
                # Wrong key (rotation) or corrupt ciphertext. Skip the row so
                # callers fall back to Settings env vars instead of 500ing the
                # admin view; mirrors `_stored_value_with_context`'s handling.
                # Log the key name only — never the ciphertext or plaintext.
                logger.warning(
                    "integration setting decrypt failed key=%s "
                    "(wrong key / corrupt row); falling back to env",
                    row.key,
                )
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
            "zalo_bot_api_base": ZALO_BOT_API_BASE,
            "zalo_oa_api_base": ZALO_OA_API_BASE,
            # Inbound OA signature verification is retired (see app/api/webhooks.py).
            "zalo_oa_webhook_signature": None,
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
            evict_local_namespace(NS_INTEGRATION_ZALO)
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
                # Reuse the process-scoped OA-token-refresh client (Tech-Lead
                # Directive §4). Kept separate from the main OA client because
                # the token endpoint lives on a different host (oauth.zaloapp.com
                # vs openapi.zalo.me) and uses a different auth shape (secret_key
                # header, not access_token). secret_key is passed per-request.
                from app.core.http import get_http_client

                client = await get_http_client(
                    "zalo_oa_token",
                    timeout=self.settings.zalo_bot_request_timeout,
                    settings=self.settings,
                )
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
            evict_local_namespace(NS_INTEGRATION_ZALO)
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
            evict_local_namespace(NS_INTEGRATION_MINIMAX)
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
            evict_local_namespace(NS_INTEGRATION_OPENROUTER)
            await bump_cache_version(NS_INTEGRATION_OPENROUTER)
        return changed

    # ── Facebook / Meta (Phase 4) ───────────────────────────────────────────

    def _fb_page_token_key(self, page_id: str) -> str:
        return f"{FB_PAGE_TOKEN_PREFIX}{page_id}"

    async def invalidate_facebook_cache(self, *, best_effort: bool = False) -> None:
        """Evict local Facebook secrets and bump the shared version counter.

        The lifecycle flow commits the DB transaction first, then treats the
        Redis version bump as best-effort so a cache failure cannot roll back a
        successful account/token/audit write.
        """
        evict_local_namespace(NS_INTEGRATION_FACEBOOK)
        if not best_effort:
            await bump_cache_version(NS_INTEGRATION_FACEBOOK)
            return
        try:
            await bump_cache_version(NS_INTEGRATION_FACEBOOK)
        except Exception:  # noqa: BLE001
            logger.warning("facebook integration cache invalidation failed", exc_info=True)

    async def resolve_facebook(self, page_id: str) -> FacebookRuntimeConfig | None:
        """Resolve the credentials for one active Page, or None if not configured.

        The Page token is decrypted with the page_id as AEAD context (Red Team
        #7): a ciphertext produced for a different Page fails to decrypt. A
        legacy v1 (non-context-bound) ciphertext is rejected so the context
        binding is enforced at runtime, not just at write time.
        """
        if not page_id:
            return None
        oauth = await self.resolve_facebook_oauth()
        token = await self._stored_value_with_context(self._fb_page_token_key(page_id), page_id)
        if not token:
            return None
        return FacebookRuntimeConfig(
            app_id=oauth.app_id,
            app_secret=oauth.app_secret,
            page_id=page_id,
            page_access_token=token,
            verify_token=oauth.verify_token,
            graph_api_version=oauth.graph_api_version,
            graph_api_base=oauth.graph_api_base,
        )

    async def resolve_facebook_oauth(self) -> FacebookOAuthConfig:
        """Resolve the app-level OAuth/webhook credentials (DB-first, env fallback).

        Cached under the Facebook namespace so admin writes invalidate via
        ``bump_cache_version(NS_INTEGRATION_FACEBOOK)``. Env vars remain the
        seed/default; DB rows override per field when non-empty.
        """
        s = self.settings

        async def _load() -> dict:
            stored = await self._stored_values(FB_SETTING_KEYS)
            return FacebookOAuthConfig(
                app_id=stored.get(FB_APP_ID) or s.meta_app_id,
                app_secret=stored.get(FB_APP_SECRET) or s.meta_app_secret,
                login_config_id=stored.get(FB_LOGIN_CONFIG_ID) or s.meta_login_config_id,
                verify_token=(stored.get(FB_WEBHOOK_VERIFY_TOKEN) or s.meta_webhook_verify_token),
                graph_api_version=s.meta_graph_api_version,
                graph_api_base=s.meta_graph_api_base,
            ).__dict__

        cached = await cached_facebook_oauth_config(_load)
        return FacebookOAuthConfig(**cached)

    async def admin_facebook_oauth_view(self) -> dict:
        """Safe status view for the admin UI (configured flag + masked preview).

        ``app_id`` and ``login_config_id`` are not secret (they appear in the
        browser OAuth URL), so the actual value is surfaced. ``app_secret`` and
        ``verify_token`` show only a masked preview like other secrets.
        """
        cfg = await self.resolve_facebook_oauth()
        return {
            "facebook_app_id": {
                "configured": bool(cfg.app_id),
                "value": cfg.app_id or None,
            },
            "facebook_app_secret": {
                "configured": bool(cfg.app_secret),
                "preview": _preview(cfg.app_secret),
            },
            "facebook_login_config_id": {
                "configured": bool(cfg.login_config_id),
                "value": cfg.login_config_id or None,
            },
            "facebook_webhook_verify_token": {
                "configured": bool(cfg.verify_token),
                "preview": _preview(cfg.verify_token),
            },
        }

    async def update_facebook_oauth(self, values: dict[str, str | None], *, actor_id) -> list[str]:
        """Persist app-level Facebook credentials. Returns the changed keys.

        ``app_id`` and ``login_config_id`` are stored as plaintext
        (``is_secret=False``); ``app_secret`` and ``verify_token`` are
        AES-GCM encrypted. Empty / whitespace-only values are ignored so a
        PUT with only some fields populated leaves the others unchanged.
        """
        changed: list[str] = []
        for key, value in values.items():
            if key not in FB_SETTING_KEYS or value is None:
                continue
            if await self._write_setting(
                key,
                str(value),
                actor_id=actor_id,
                is_secret=key in FB_SECRET_KEYS,
            ):
                changed.append(key)

        if changed:
            await record_audit(
                self.db,
                action="update_facebook_integration_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="facebook",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
            evict_local_namespace(NS_INTEGRATION_FACEBOOK)
            await bump_cache_version(NS_INTEGRATION_FACEBOOK)
        return changed

    async def _stored_value_with_context(self, key: str, context: str) -> str:
        """Fetch one encrypted setting row and decrypt with AEAD context.

        Page tokens must be context-bound (``v2:``); a legacy ``v1:`` row is
        rejected as corrupt so a token moved between Pages cannot decrypt via
        the context-less fallback (Red Team #7).
        """
        if not hasattr(self.db, "scalars"):
            return ""
        row = await self.db.scalar(select(IntegrationSetting).where(IntegrationSetting.key == key))
        if row is None:
            return ""
        stored = row.encrypted_value or ""
        if not stored.startswith("v2:"):
            # A v1 row for a Page token is either a corrupt write or a legacy
            # import. Fail closed (reconnect required) rather than decrypting
            # without the context binding.
            logger.warning("facebook page token rejected (not context-bound) key=%s", key)
            return ""
        try:
            return self.cipher.decrypt_with_context(stored, context)
        except Exception:  # noqa: BLE001 — wrong-context / corrupt ciphertext
            # A token moved between Pages or a rotated encryption key. Surface
            # as "not resolvable" so the caller fails closed (reconnect required).
            logger.warning(
                "facebook page token decrypt failed key=%s (wrong context or corrupt)",
                key,
            )
            return ""

    async def stage_facebook_page_token_upsert(
        self, page_id: str, token: str, *, updated_by
    ) -> None:
        """Stage one Page access token with page_id-bound ciphertext.

        Writes the row directly (NOT via ``_write_setting``) so the pre-sealed
        ``v2:`` ciphertext is stored verbatim — ``_write_setting`` would
        double-encrypt it. The caller owns commit/rollback so this can compose
        with other writes inside a single transaction.
        """
        from datetime import datetime, timezone

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        sealed = self.cipher.encrypt_with_context(token, page_id)
        key = self._fb_page_token_key(page_id)
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(IntegrationSetting)
            .values(
                key=key,
                encrypted_value=sealed,
                is_secret=True,
                updated_by=updated_by,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "encrypted_value": sealed,
                    "is_secret": True,
                    "updated_by": updated_by,
                    "updated_at": now,
                },
            )
        )
        await self.db.execute(stmt)

    async def set_facebook_page_token(self, page_id: str, token: str, *, updated_by) -> None:
        """Persist one Page access token with page_id-bound ciphertext."""
        await self.stage_facebook_page_token_upsert(page_id, token, updated_by=updated_by)
        await self.db.commit()
        await self.invalidate_facebook_cache()

    async def stage_facebook_page_token_delete(self, page_id: str) -> None:
        """Stage deletion of one Page token without committing the session."""
        from sqlalchemy import delete as sa_delete

        await self.db.execute(
            sa_delete(IntegrationSetting).where(
                IntegrationSetting.key == self._fb_page_token_key(page_id)
            )
        )

    async def clear_facebook_page_token(self, page_id: str) -> None:
        """Remove one Page token (disconnect). History is never deleted."""
        await self.stage_facebook_page_token_delete(page_id)
        await self.db.commit()
        await self.invalidate_facebook_cache()
