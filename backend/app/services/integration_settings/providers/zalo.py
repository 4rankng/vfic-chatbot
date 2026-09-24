"""Zalo provider group: Bot + OA credentials, admin view, and OA token refresh."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from app.core.cache import bump_cache_version
from app.core.config import ZALO_BOT_API_BASE, ZALO_OA_API_BASE
from app.core.preamble_cache import NS_INTEGRATION_ZALO, cached_zalo_config, evict_local_namespace
from app.models.integration import IntegrationSetting
from app.services.audit_service import record_audit
from app.services.integration_settings._shared import _secret_status

logger = logging.getLogger(__name__)

# OA OAuth token endpoint (grant_type=authorization_code | refresh_token).
# Access tokens are opaque and valid for 25 hours; refresh tokens are valid for
# three months but single-use. Refresh on demand and persist every rotated pair.
ZALO_OA_TOKEN_URL = "https://oauth.zaloapp.com/v4/oa/access_token"

# Redis lock guarding the OA refresh. The refresh token is single-use, so two
# concurrent redeemers leave the loser's stale pair overwriting the winner's and
# the OA access token invalid until an admin re-authorizes.
ZALO_OA_REFRESH_LOCK_KEY = "zalo:oa:token:refresh"
# Headroom on top of the request budget for the persist + commit that follow the
# refresh POST.
_OA_REFRESH_LOCK_HEADROOM_SECONDS = 30


def _oa_refresh_lock_ttl(request_timeout: int) -> int:
    """Lock TTL above the work the lock guards (REL-03).

    The guarded work is the caller's failed send plus the refresh POST — each
    bounded by ``zalo_bot_request_timeout`` — and then the write + commit of the
    rotated pair. A TTL shorter than that budget expires mid-flight, letting a
    second worker acquire the lock and redeem the same single-use refresh token.
    """
    return 2 * max(int(request_timeout), 1) + _OA_REFRESH_LOCK_HEADROOM_SECONDS


ZALO_BOT_TOKEN = "zalo_bot_token"
ZALO_BOT_WEBHOOK_SECRET = "zalo_bot_webhook_secret"
ZALO_OA_APP_ID = "zalo_oa_app_id"
ZALO_OA_SECRET_KEY = "zalo_oa_secret_key"
ZALO_OA_ACCESS_TOKEN = "zalo_oa_access_token"
ZALO_OA_REFRESH_TOKEN = "zalo_oa_refresh_token"

ZALO_SETTING_KEYS = (
    ZALO_BOT_TOKEN,
    ZALO_BOT_WEBHOOK_SECRET,
    ZALO_OA_APP_ID,
    ZALO_OA_SECRET_KEY,
    ZALO_OA_ACCESS_TOKEN,
    ZALO_OA_REFRESH_TOKEN,
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


class ZaloSettingsMixin:
    """Resolve/admin/persist for the two Zalo channels (Bot + OA)."""

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
            "zalo_bot_token": _secret_status(cfg.bot_token),
            "zalo_bot_webhook_secret": _secret_status(cfg.bot_webhook_secret),
            "zalo_oa_app_id": {
                "configured": bool(cfg.oa_app_id),
                "value": cfg.oa_app_id or None,
            },
            "zalo_oa_secret_key": _secret_status(cfg.oa_secret_key),
            "zalo_oa_access_token": _secret_status(cfg.oa_access_token),
            "zalo_oa_refresh_token": _secret_status(cfg.oa_refresh_token),
            "zalo_bot_api_base": ZALO_BOT_API_BASE,
            "zalo_oa_api_base": ZALO_OA_API_BASE,
            # Inbound OA signature verification is retired (see app/api/webhooks.py).
            "zalo_oa_webhook_signature": None,
        }

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
        parallel; losers re-read whatever token the winner just stored. The lock
        value is a per-holder UUID and the release is a Lua compare-and-delete,
        so a straggler whose TTL expired cannot delete a successor's lock and
        admit a third redeemer of the single-use refresh token (REL-03). Returns
        the new access_token, or ``None`` on any failure — the caller then
        surfaces the original send error.
        """

        from app.core.redis import get_redis

        cfg = await self.resolve_zalo()
        if not cfg.oa_refresh_token:
            return None

        redis = get_redis()
        lock_key = ZALO_OA_REFRESH_LOCK_KEY
        leader_id = uuid.uuid4().hex
        try:
            acquired = await redis.set(
                lock_key,
                leader_id,
                nx=True,
                ex=_oa_refresh_lock_ttl(self.settings.zalo_bot_request_timeout),
            )
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
            # Delete the marker only while we still own it (Lua CAS): a holder
            # that outlived its TTL must never delete a successor's lock.
            try:
                await redis.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] "
                    "then return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    lock_key,
                    leader_id,
                )
            except Exception:  # noqa: BLE001
                logger.warning("zalo OA token refresh lock cleanup failed", exc_info=True)
