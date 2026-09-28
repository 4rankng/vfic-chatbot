"""Facebook / Meta provider group: app credentials and per-Page tokens.

Page tokens are sealed with page_id-bound AEAD context (Red Team #7) and the
app-level secrets are revealed only through the audited step-up flow (SEC-07).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging
from dataclasses import dataclass

from app.core.cache import bump_cache_version
from app.core.preamble_cache import (
    NS_INTEGRATION_FACEBOOK,
    cached_facebook_oauth_config,
    evict_local_namespace,
)
from app.core.security import verify_password
from app.models.integration import IntegrationSetting
from app.services.audit_service import record_audit
from app.services.integration_settings._shared import _secret_status
from app.shared.domain.errors import BadRequestError

logger = logging.getLogger(__name__)

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

# Step-up re-authentication failure message for the plaintext reveal (SEC-07).
_FB_REVEAL_STEP_UP_FAILED = "Mật khẩu xác nhận không đúng"


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


class FacebookSettingsMixin:
    """Resolve/admin/persist for the Meta App credentials + per-Page tokens."""

    if TYPE_CHECKING:
        # Supplied by IntegrationSettingsService, the class that mixes these in.
        # Declarations only: TYPE_CHECKING is False at runtime, so nothing here is
        # ever assigned and the composed class stays the single source of truth.
        db: AsyncSession
        settings: Settings
        cipher: IntegrationSettingsCipher

        async def _stored_values(self, keys: Iterable[str]) -> dict[str, str]: ...

        async def _write_setting(
            self,
            key: str,
            value: str,
            *,
            actor_id: object | None = None,
            is_secret: bool,
        ) -> bool: ...

        async def _stored_value_with_context(self, key: str, context: str) -> str: ...

        from collections.abc import Iterable

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.config import Settings
        from app.services.integration_settings.cipher import IntegrationSettingsCipher

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
        """Safe status view for the admin UI (configured flag + status, no secret characters).

        ``app_id`` and ``login_config_id`` are not secret (they appear in the
        browser OAuth URL), so the actual value is surfaced. ``app_secret`` and
        ``verify_token`` are authorizing secrets and report status only — a
        character preview here would leak the HMAC key that authenticates every
        inbound Messenger webhook (SEC-07).
        """
        cfg = await self.resolve_facebook_oauth()
        return {
            "facebook_app_id": {
                "configured": bool(cfg.app_id),
                "value": cfg.app_id or None,
            },
            "facebook_app_secret": _secret_status(cfg.app_secret),
            "facebook_login_config_id": {
                "configured": bool(cfg.login_config_id),
                "value": cfg.login_config_id or None,
            },
            "facebook_webhook_verify_token": _secret_status(cfg.verify_token),
        }

    async def reveal_facebook_oauth(
        self, *, actor_id, password: str, password_hash: str
    ) -> FacebookOAuthConfig:
        """Resolve the app-level Meta secrets for one audited, step-up reveal.

        SEC-07: the plaintext leaves this process only after the actor re-proves
        possession of their password. A hijacked admin session — a token lifted
        from localStorage — must not be enough on its own to read the Meta app
        secret, the HMAC key that authenticates every inbound Messenger webhook.
        The reveal is audit-logged with its actor; the values themselves are
        never logged. Raises ``BadRequestError`` when the re-entry fails.
        """
        if not password_hash or not await verify_password(password, password_hash):
            raise BadRequestError(_FB_REVEAL_STEP_UP_FAILED)

        cfg = await self.resolve_facebook_oauth()
        await record_audit(
            self.db,
            action="reveal_facebook_credentials",
            actor_id=actor_id,
            target_type="integration_settings",
            target_id="facebook",
            payload={
                "revealed": [
                    key
                    for key, value in (
                        (FB_APP_SECRET, cfg.app_secret),
                        (FB_WEBHOOK_VERIFY_TOKEN, cfg.verify_token),
                    )
                    if value
                ]
            },
        )
        await self.db.commit()
        return cfg

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
