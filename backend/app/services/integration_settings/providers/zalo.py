"""Zalo provider group: Bot + OA credentials, admin view, and OA token refresh."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import asyncio
import logging
import uuid
from dataclasses import dataclass

from app.channels.types import TINGTING_OA_ACCOUNT_KEY
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

# The original OA (the one Alembic 0047 seeded) keeps the singleton keys above.
# Every additional OA stores the same four credentials under ``<key>:<oa_id>``,
# mirroring ``facebook_page_token:<page id>`` for multi-Page Messenger.
ZALO_OA_DEFAULT_ACCOUNT_KEY = "default:zalo_oa"
ZALO_OA_ACCOUNT_SETTING_BASES = (
    ZALO_OA_APP_ID,
    ZALO_OA_SECRET_KEY,
    ZALO_OA_ACCESS_TOKEN,
    ZALO_OA_REFRESH_TOKEN,
)


def oa_account_setting_key(base: str, account_key: str) -> str:
    """Storage key for one OA account's credential (``zalo_oa_access_token:<oa id>``)."""
    return f"{base}:{account_key}"


def is_oa_account_setting_key(key: str) -> bool:
    """True for a per-OA credential key (never the singleton or a Bot key)."""
    return any(
        key.startswith(f"{base}:") and key != base for base in ZALO_OA_ACCOUNT_SETTING_BASES
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

    async def resolve_zalo(self, account_key: str | None = None) -> ZaloRuntimeConfig:
        """Resolve the Zalo Bot + OA runtime config.

        ``account_key`` selects one OA account: a second OA keeps its own four
        credentials under ``zalo_oa_*:<oa id>``. A non-default account resolves
        ONLY its own stored values — it must never inherit the original OA's
        token, or replies would leave as the wrong brand. An account with no
        stored credentials resolves empty and the senders fail closed. The
        default account (and every caller that omits the key) resolves the
        singleton keys exactly as before.
        """
        account_key = account_key or ZALO_OA_DEFAULT_ACCOUNT_KEY
        is_default = account_key == ZALO_OA_DEFAULT_ACCOUNT_KEY

        async def _load() -> dict:
            keys = list(ZALO_SETTING_KEYS)
            if not is_default:
                keys += [
                    oa_account_setting_key(base, account_key)
                    for base in ZALO_OA_ACCOUNT_SETTING_BASES
                ]
            stored = await self._stored_values(keys)

            def _oa(base: str, env_fallback: str) -> str:
                if not is_default:
                    return stored.get(oa_account_setting_key(base, account_key), "")
                return stored.get(base) or env_fallback

            return ZaloRuntimeConfig(
                bot_token=stored.get(ZALO_BOT_TOKEN) or self.settings.zalo_bot_token,
                bot_webhook_secret=(
                    stored.get(ZALO_BOT_WEBHOOK_SECRET) or self.settings.zalo_bot_webhook_secret
                ),
                oa_app_id=_oa(ZALO_OA_APP_ID, self.settings.zalo_oa_app_id),
                oa_secret_key=_oa(ZALO_OA_SECRET_KEY, self.settings.zalo_oa_secret_key),
                oa_access_token=_oa(ZALO_OA_ACCESS_TOKEN, self.settings.zalo_oa_access_token),
                oa_refresh_token=_oa(ZALO_OA_REFRESH_TOKEN, self.settings.zalo_oa_refresh_token),
            ).__dict__

        cached = await cached_zalo_config(_load, account_key=account_key)
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
        if key not in ZALO_SETTING_KEYS and not is_oa_account_setting_key(key):
            return False
        if value is None:
            return False
        cleaned = value.strip()
        if not cleaned:
            return False
        encrypted = self.cipher.encrypt(cleaned)
        is_secret = key.split(":", 1)[0] != ZALO_OA_APP_ID
        row = await self.db.get(IntegrationSetting, key)
        if row is None:
            row = IntegrationSetting(
                key=key,
                encrypted_value=encrypted,
                is_secret=is_secret,
                updated_by=actor_id,
            )
            self.db.add(row)
        else:
            row.encrypted_value = encrypted
            row.is_secret = is_secret
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

    async def oa_account_credentials_view(self, account_key: str) -> dict:
        """Masked credential status for one OA account (never a raw secret)."""
        cfg = await self.resolve_zalo(account_key)
        return {
            "account_key": account_key,
            "app_id": cfg.oa_app_id or "",
            "app_id_configured": bool(cfg.oa_app_id),
            "secret_key": _secret_status(cfg.oa_secret_key),
            "access_token": _secret_status(cfg.oa_access_token),
            "refresh_token": _secret_status(cfg.oa_refresh_token),
        }

    async def oa_account_token_updated_at(self, account_key: str) -> str | None:
        """The stored per-account access token's last update (ISO, non-secret).

        The one credential fact the console may show for the TingTing account:
        WHEN the payroll-owned token last landed (push or pull), never the
        token itself.
        """
        row = await self.db.get(
            IntegrationSetting,
            oa_account_setting_key(ZALO_OA_ACCESS_TOKEN, account_key),
        )
        if row is None or row.updated_at is None:
            return None
        return row.updated_at.isoformat()

    async def write_oa_account_credentials(
        self, account_key: str, values: dict[str, str | None], *, actor_id
    ) -> list[str]:
        """Stage one OA account's namespaced credentials. The caller commits.

        ``values`` is keyed by the base setting name (``zalo_oa_access_token``
        …). Only the four OA credential bases are accepted: a typo cannot write
        an arbitrary integration row.
        """
        changed: list[str] = []
        for base, value in values.items():
            if base not in ZALO_OA_ACCOUNT_SETTING_BASES:
                continue
            if await self._write_secret(
                oa_account_setting_key(base, account_key), value, actor_id=actor_id
            ):
                changed.append(base)
        return changed

    async def clear_oa_account_credentials(self, account_key: str) -> int:
        """Delete one OA account's namespaced credential rows. The caller commits."""
        from sqlalchemy import delete

        from app.models.integration import IntegrationSetting

        keys = [
            oa_account_setting_key(base, account_key)
            for base in ZALO_OA_ACCOUNT_SETTING_BASES
        ]
        result = await self.db.execute(
            delete(IntegrationSetting).where(IntegrationSetting.key.in_(keys))
        )
        # rowcount is a CursorResult member; the execute() result is typed as
        # the wider Result[Any] the session hands back.
        from sqlalchemy import CursorResult

        return int(cast(CursorResult[Any], result).rowcount or 0)

    async def _alert_refresh_rejected(self, account_key: str | None, data: object) -> None:
        """Push the one alert that matters when an OA credential dies.

        A refused refresh token is silent and terminal: every send on that OA
        keeps failing with "Access token has expired" and only an operator can
        re-authorize the channel. Deduped per account (see ``notify_admins``), so
        a refresh attempted on every turn does not become a push per turn.
        Best-effort: an alert must never break the refresh path it reports on.
        """
        try:
            from app.services.push import notify_admins

            error_name = data.get("error_name") if isinstance(data, dict) else None
            await notify_admins(
                self.db,
                title="Zalo OA cần cấp lại quyền",
                body=(
                    f"Refresh token của OA '{account_key or 'mặc định'}' bị Zalo từ chối"
                    f" ({error_name or 'không rõ lý do'}). Không thể gửi tin nhắn trên OA này"
                    " cho tới khi cấp lại quyền trong Cài đặt → Zalo OA."
                ),
                url="/settings",
                tag=f"zalo-oa-token-{account_key or 'default'}",
                dedupe_key=f"zalo-oa-refresh:{account_key or 'default'}",
            )
        except Exception:  # noqa: BLE001 — an alert must not break token refresh
            logger.warning("zalo OA refresh alert push failed", exc_info=True)

    async def _alert_payroll_token_unavailable(self) -> None:
        """The TingTing-account twin of ``_alert_refresh_rejected``.

        When payroll cannot serve the token, every send on that OA keeps
        failing and only payroll's recovery fixes it — the operator needs to
        know which side is broken. Deduped under the same per-account
        namespace as the Zalo-branch alert, so a refresh attempted on every
        turn does not become a push per turn. Best-effort.
        """
        try:
            from app.services.push import notify_admins

            await notify_admins(
                self.db,
                title="Không lấy được token Zalo OA TingTing",
                body=(
                    "Payroll chưa trả được Access Token cho OA TingTing. Tin nhắn trên OA này "
                    "sẽ gửi thất bại cho tới khi payroll phục hồi (kiểm tra khoản tích hợp "
                    "Zalo của payroll)."
                ),
                url="/settings",
                tag=f"zalo-oa-token-{TINGTING_OA_ACCOUNT_KEY}",
                dedupe_key=f"zalo-oa-refresh:{TINGTING_OA_ACCOUNT_KEY}",
            )
        except Exception:  # noqa: BLE001 — an alert must not break token refresh
            logger.warning("tingting OA payroll-token alert push failed", exc_info=True)

    async def _pull_tingting_oa_token_from_payroll(self) -> str | None:
        """The TingTing branch of ``refresh_oa_access_token``: pull from payroll.

        Payroll solely owns and rotates this account's token pair (owner
        ruling 2026-10-07). The stored ``zalo_oa_refresh_token`` for this
        account is a fossil no one may redeem again, so instead of the Zalo
        OAuth POST the fresh access token is pulled from payroll's
        ``GET /api/v1/integration/zalo/token`` and stored under the same
        per-account key the push webhook (``POST /webhooks/zalo-oa-token``)
        writes. Returns the new token, or ``None`` on any failure — the same
        contract the Zalo branch gives its callers.

        No Redis lock guards the pull, deliberately: the Zalo branch's lock
        serializes redeemers of a single-use refresh token, while a pull is
        idempotent — concurrent workers all store the identical token, and the
        loser of a race costs one redundant GET. ``failure`` alerts are
        deduped, so a pull per send attempt cannot become an alert storm.
        """
        from app.services.tingting_api import TingtingApiService

        token = await TingtingApiService(
            self.db, settings=self.settings, cipher=self.cipher
        ).fetch_zalo_oa_access_token()
        if not token:
            await self._alert_payroll_token_unavailable()
            return None
        await self._write_secret(
            oa_account_setting_key(ZALO_OA_ACCESS_TOKEN, TINGTING_OA_ACCOUNT_KEY), token
        )
        # Persist before nonessential work, like the Zalo branch: a lost token
        # here means every send on the OA keeps failing until the next pull.
        await self.db.commit()
        evict_local_namespace(NS_INTEGRATION_ZALO)
        try:
            await record_audit(
                self.db,
                action="refresh_zalo_oa_token",
                actor_id=None,
                target_type="integration_settings",
                target_id="zalo",
                payload={"account_key": TINGTING_OA_ACCOUNT_KEY, "source": "payroll"},
            )
            await self.db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("tingting OA payroll token pull audit failed", exc_info=True)
        try:
            await bump_cache_version(NS_INTEGRATION_ZALO)
        except Exception:  # noqa: BLE001
            logger.warning("tingting OA payroll token pull cache invalidation failed", exc_info=True)
        return token

    async def refresh_oa_access_token(self, account_key: str | None = None) -> str | None:
        """Refresh one OA account's access_token from its stored refresh_token.

        Called lazily by ``ZaloOASender`` when a send reports the token invalid.
        A Redis ``SET NX EX`` lock prevents RQ workers from refreshing in
        parallel; losers re-read whatever token the winner just stored. The lock
        value is a per-holder UUID and the release is a Lua compare-and-delete,
        so a straggler whose TTL expired cannot delete a successor's lock and
        admit a third redeemer of the single-use refresh token (REL-03). Returns
        the new access_token, or ``None`` on any failure — the caller then
        surfaces the original send error.

        ``account_key`` scopes both the credentials and the lock: each OA has
        its own single-use refresh token, so two OAs must never share a lock
        (one would block the other's legitimate refresh).

        The TingTing support OA never reaches the Zalo OAuth branch: payroll
        solely owns and rotates that account's token pair, so its "refresh"
        is a pull from payroll instead (see
        :meth:`_pull_tingting_oa_token_from_payroll`).
        """

        from app.core.redis import async_value, get_redis

        account_key = account_key or ZALO_OA_DEFAULT_ACCOUNT_KEY
        if account_key == TINGTING_OA_ACCOUNT_KEY:
            return await self._pull_tingting_oa_token_from_payroll()
        is_default = account_key == ZALO_OA_DEFAULT_ACCOUNT_KEY

        def _key(base: str) -> str:
            return base if is_default else oa_account_setting_key(base, account_key)

        cfg = await self.resolve_zalo(account_key)
        if not cfg.oa_refresh_token:
            logger.warning(
                "zalo OA token refresh skipped: no stored refresh token "
                f"(account_key={account_key}) — re-link the OA in settings"
            )
            return None

        redis = get_redis()
        lock_key = (
            ZALO_OA_REFRESH_LOCK_KEY
            if is_default
            else f"{ZALO_OA_REFRESH_LOCK_KEY}:{account_key}"
        )
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
            access_key = _key(ZALO_OA_ACCESS_TOKEN)
            for _ in range(20):
                await asyncio.sleep(0.1)
                stored = await self._stored_values((access_key,))
                refreshed = stored.get(access_key)
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
                # Zalo rejected the refresh (e.g. -14014 "Invalid refresh token."
                # when the stored single-use token was already redeemed or
                # expired). Surface the provider's own error fields — the body
                # carries no secrets — so ops can see WHY without re-deriving.
                logger.warning(
                    "zalo OA token refresh rejected by provider "
                    f"(account_key={account_key}, "
                    f"error={data.get('error') if isinstance(data, dict) else 'non-json'}, "
                    f"error_name={data.get('error_name') if isinstance(data, dict) else '-'}, "
                    f"error_description={data.get('error_description') if isinstance(data, dict) else '-'})"
                )
                await self._alert_refresh_rejected(account_key, data)
                return None

            new_access = str(data["access_token"])
            await self._write_secret(_key(ZALO_OA_ACCESS_TOKEN), new_access)
            if data.get("refresh_token"):
                await self._write_secret(_key(ZALO_OA_REFRESH_TOKEN), str(data["refresh_token"]))
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
                    payload={
                        "rotated_refresh_token": bool(data.get("refresh_token")),
                        "account_key": account_key,
                    },
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
                await async_value(
        redis.eval(
                        "if redis.call('get', KEYS[1]) == ARGV[1] "
                        "then return redis.call('del', KEYS[1]) else return 0 end",
                        1,
                        lock_key,
                        leader_id,
                    )
        )
            except Exception:  # noqa: BLE001
                logger.warning("zalo OA token refresh lock cleanup failed", exc_info=True)
