"""The TingTing employee-support Zalo OA: link, verify, and serve.

One channel account (`zalo_oa` / ``tingting``) whose four Zalo credentials live
under the standard per-account namespace (``zalo_oa_*:tingting``). The admin
never types an OA id: the values are probed with Zalo's ``getoa`` on save, which
returns the OA's own id and display name. The discovered id is what inbound
routing matches (``ZaloOaAccountResolver``) and what the reset-flow gate pins, so
the flow runs on this OA and nowhere else.

Everything the probe learns is provider-safe (id, name, timestamp, redacted
error) and lives in the channel account's ``provider_metadata``; credentials stay
encrypted in ``integration_settings``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import types as ct
from app.channels.accounts import ChannelAccountStatus
from app.channels.types import TINGTING_OA_ACCOUNT_KEY
from app.channels.providers.zalo_account import acquire_zalo_oa_account_lock
from app.models.channel_account import ChannelAccount
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

TINGTING_OA_DEFAULT_LABEL = "Ting Ting Software Solution"

# Credential bases the admin card edits (all four live under the account).
TINGTING_OA_CREDENTIAL_BASES = (
    "zalo_oa_app_id",
    "zalo_oa_secret_key",
    "zalo_oa_access_token",
    "zalo_oa_refresh_token",
)

# Zalo rejects a single-use refresh token that was already redeemed or has
# expired (-14014). Nothing in this app can revive one — only a fresh
# authorization from the OA dashboard can. Said plainly to the operator, because
# a link that stores a dead pair is exactly how the 2026-09-28 sends failed.
OA_REFRESH_REJECTED_ERROR = (
    "OA Refresh Token bị Zalo từ chối khi rotation (thường là -14014: token đã "
    "bị dùng hoặc đã hết hạn). Vào OA dashboard Zalo lấy cặp Access Token + "
    "Refresh Token MỚI rồi lưu lại."
)


class TingtingOaLinkError(ValueError):
    """The submitted credentials cannot serve as the support OA (→ 422)."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(message: str, secrets: Iterable[str]) -> str:
    """Strip any credential the provider echoed back, and bound the length."""
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    message = message.strip() or "unknown error"
    return f"{message[:237]}..." if len(message) > 240 else message


def _link_secrets(*sources: dict[str, str | None]) -> set[str]:
    """Every credential a provider error could echo, from every value in play.

    The admin's posted values, the values left in force, and any token a
    rotation returns all reach ``oa_last_error`` if unredacted — and that field
    is admin-visible and persisted in ``provider_metadata``.
    """
    secrets: set[str] = set()
    for source in sources:
        for value in source.values():
            cleaned = str(value or "").strip()
            if cleaned:
                secrets.add(cleaned)
    return secrets


async def processing_enabled(db: AsyncSession) -> bool:
    """Whether candidate messages on the TingTing OA are processed at all.

    The admin kill switch (Settings → TingTing, key ``tingting_oa_enabled``):
    ``False`` makes the worker stand every turn on that OA down before the
    graph runs — no LLM call, no reply. Absent row means enabled, so an
    install that never touched the switch keeps working. A read failure fails
    OPEN (logged): a settings outage must never silently silence the bot.
    """
    from app.services.integration_settings import IntegrationSettingsService

    try:
        return await IntegrationSettingsService(db).resolve_tingting_oa_enabled()
    except Exception:  # noqa: BLE001 — fail open on a broken settings read
        logger.warning("tingting oa enabled read failed; processing stays on", exc_info=True)
        return True


class TingtingOaLinkService:
    """Link (and re-check) the Zalo OA that serves the employee reset flow."""

    def __init__(self, db: AsyncSession, *, settings=None, cipher=None) -> None:
        self.db = db
        self._settings = settings
        self._cipher = cipher

    # --- wiring helpers -------------------------------------------------
    def _settings_service(self):
        from app.services.integration_settings import IntegrationSettingsService

        return IntegrationSettingsService(
            self.db, settings=self._settings, cipher=self._cipher
        )

    async def _account(self) -> ChannelAccount | None:
        return await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == ct.PROVIDER_ZALO_OA,
                ChannelAccount.account_key == TINGTING_OA_ACCOUNT_KEY,
            )
        )

    async def _metadata(self) -> dict[str, Any]:
        row = await self._account()
        if row is None or not isinstance(row.provider_metadata, dict):
            return {}
        return dict(row.provider_metadata)

    # --- reads used by routing and the reset gate -----------------------
    async def verified_oa_id(self) -> str:
        """The linked OA's own id, or "" when the link is unverified/inactive."""
        row = await self._account()
        if row is None or not row.is_active:
            return ""
        oa_id = (row.provider_metadata or {}).get("oa_id")
        return str(oa_id or "")

    async def is_verified(self) -> bool:
        return bool(await self.verified_oa_id())

    async def view(self) -> dict:
        """Admin card projection: credential statuses + link state."""

        settings_service = self._settings_service()
        row = await self._account()
        metadata = await self._metadata()
        credentials = await settings_service.oa_account_credentials_view(
            TINGTING_OA_ACCOUNT_KEY
        )
        return {
            "oa_app_id": credentials["app_id"] or "",
            "oa_secret_key": credentials["secret_key"],
            "oa_access_token": credentials["access_token"],
            "oa_refresh_token": credentials["refresh_token"],
            "oa_linked": bool(row is not None and row.is_active and metadata.get("oa_id")),
            "oa_id": str(metadata.get("oa_id") or ""),
            "oa_name": str(metadata.get("name") or ""),
            "oa_label": (row.label if row is not None else "") or "",
            "oa_verified_at": metadata.get("verified_at"),
            "oa_last_error": metadata.get("last_error") or "",
            "oa_last_checked_at": metadata.get("last_checked_at"),
        }

    # --- mutation -------------------------------------------------------
    async def link(self, values: dict[str, str | None], *, actor_id: Any = None) -> dict:
        """Store the four credentials, prove they work, and register the account.

        ``values`` is tri-state per field: absent keeps the stored value, ``""``
        clears it. Every step runs against the *effective* credentials (posted,
        else stored).

        The link is proven, not assumed: Zalo's ``getoa`` discovers the OA id (no
        OA id is ever typed) and the access token is rotated **once** through the
        same provider call the default OA uses, so a refresh token that is dead
        or belongs to another authorization fails here instead of silently
        breaking every send a day later.

        A failure still stores what was typed — the admin fixes one field and
        saves again — but the account is not registered and the reset flow stays
        off, so a bad link can never serve employees. Note the rotation commits
        the staged credential write as a side effect, which is what makes
        "stored even when the link fails" true.
        """
        settings_service = self._settings_service()
        # Omitted fields keep the stored value, so the probe runs against the
        # *effective* credentials — the decrypted runtime config, not the masked
        # admin view (which only reports whether a value exists).
        stored = await settings_service.resolve_zalo(TINGTING_OA_ACCOUNT_KEY)
        existing = {
            "zalo_oa_app_id": stored.oa_app_id,
            "zalo_oa_secret_key": stored.oa_secret_key,
            "zalo_oa_access_token": stored.oa_access_token,
            "zalo_oa_refresh_token": stored.oa_refresh_token,
        }
        effective: dict[str, str] = {}
        for base in TINGTING_OA_CREDENTIAL_BASES:
            posted = values.get(base, None)
            effective[base] = (
                existing[base] if posted is None else str(posted).strip()
            )

        if not effective["zalo_oa_access_token"]:
            raise TingtingOaLinkError("cần OA Access Token của Zalo OA TingTing")
        # Without a refresh token the pair cannot outlive the 25-hour access
        # token, so refuse before probing rather than discover it in a day.
        if not effective["zalo_oa_refresh_token"]:
            raise TingtingOaLinkError("cần OA Refresh Token của Zalo OA TingTing")

        touched: dict[str, str | None] = {
            base: value for base, value in effective.items() if values.get(base) is not None
        }
        if touched:
            await settings_service.write_oa_account_credentials(
                TINGTING_OA_ACCOUNT_KEY, touched, actor_id=actor_id
            )
            # The credential write only stages, and the rotation below reads the
            # pair back through a SELECT — flush explicitly so it redeems the
            # value just saved instead of the previously stored one.
            await self.db.flush()

        # Posted values, the values in force, and whatever the rotation returns
        # may all be echoed back; none may survive into oa_last_error.
        secrets = _link_secrets(values, existing, effective)

        # The probe is what discovers the OA id: no OA id is ever typed.
        probe = await self._probe(effective, secrets)

        # Exactly one rotation per link, always attempted. Zalo refresh tokens
        # are single-use, so a second call would redeem a second token for
        # nothing. A rejection is the root cause of a failing link and is
        # reported as such even when the probe happened to pass: on 2026-09-28 a
        # pair was stored at 07:48 whose refresh token was already dead, and the
        # first send failed 25 hours later with -14014. Rotating here is what
        # turns that silent day-later outage into an error the admin sees now.
        new_token = await settings_service.refresh_oa_access_token(
            TINGTING_OA_ACCOUNT_KEY
        )
        if not new_token:
            probe = {
                "ok": False,
                "oa_id": "",
                "name": "",
                "error": OA_REFRESH_REJECTED_ERROR,
            }
        else:
            secrets.add(new_token.strip())
            if not probe["ok"]:
                # The pasted access token was simply expired while the pair is
                # healthy — re-probe with the freshly rotated one, exactly like
                # the runtime send path does.
                effective["zalo_oa_access_token"] = new_token
                probe = await self._probe(effective, secrets)

        await acquire_zalo_oa_account_lock(self.db, shared=False)
        row = await self._account()
        metadata = dict((row.provider_metadata if row is not None else {}) or {})
        metadata["last_checked_at"] = _utcnow_iso()
        if probe["ok"]:
            metadata["oa_id"] = probe["oa_id"]
            metadata["name"] = probe["name"]
            metadata["verified_at"] = _utcnow_iso()
            metadata.pop("last_error", None)
            if row is None:
                row = ChannelAccount(
                    provider=ct.PROVIDER_ZALO_OA,
                    account_key=TINGTING_OA_ACCOUNT_KEY,
                    label=probe["name"] or TINGTING_OA_DEFAULT_LABEL,
                    status=ChannelAccountStatus.ACTIVE,
                    generation=1,
                )
                self.db.add(row)
            else:
                if not row.is_active:
                    row.generation = int(row.generation or 0) + 1
                row.status = ChannelAccountStatus.ACTIVE
                row.label = probe["name"] or row.label or TINGTING_OA_DEFAULT_LABEL
            row.provider_metadata = metadata
            # The reset-flow binding follows the verified link, never a typed id.
            await settings_service.update_tingting(
                {"reset_oa_id": TINGTING_OA_ACCOUNT_KEY}, actor_id=actor_id
            )
        else:
            # A failed probe is still a status worth keeping: the admin card shows
            # why the link did not happen. The row is created INACTIVE (so it can
            # neither route events nor send) when this is the first attempt.
            metadata["last_error"] = probe["error"]
            if row is None:
                row = ChannelAccount(
                    provider=ct.PROVIDER_ZALO_OA,
                    account_key=TINGTING_OA_ACCOUNT_KEY,
                    label=TINGTING_OA_DEFAULT_LABEL,
                    status=ChannelAccountStatus.INACTIVE,
                    generation=0,
                    provider_metadata=metadata,
                )
                self.db.add(row)
            else:
                row.provider_metadata = metadata

        await record_audit(
            self.db,
            action="link_tingting_oa",
            actor_id=actor_id,
            target_type="channel_account",
            target_id=TINGTING_OA_ACCOUNT_KEY,
            payload={
                "verified": probe["ok"],
                "oa_id": probe["oa_id"] if probe["ok"] else "",
                "changed_keys": sorted(touched),
            },
        )
        await self.db.commit()
        await self._bump_cache()
        return await self.view()

    async def unlink(self, *, actor_id: Any = None) -> dict:
        """Drop the credentials and deactivate the support OA."""
        settings_service = self._settings_service()
        await acquire_zalo_oa_account_lock(self.db, shared=False)
        row = await self._account()
        if row is not None:
            row.status = ChannelAccountStatus.INACTIVE
            row.generation = int(row.generation or 0) + 1
            metadata = dict(row.provider_metadata or {})
            metadata.pop("oa_id", None)
            row.provider_metadata = metadata
        cleared = await settings_service.clear_oa_account_credentials(
            TINGTING_OA_ACCOUNT_KEY
        )
        await settings_service.update_tingting({"reset_oa_id": ""}, actor_id=actor_id)
        await record_audit(
            self.db,
            action="unlink_tingting_oa",
            actor_id=actor_id,
            target_type="channel_account",
            target_id=TINGTING_OA_ACCOUNT_KEY,
            payload={"cleared_credentials": cleared},
        )
        await self.db.commit()
        await self._bump_cache()
        return await self.view()

    # --- probe ----------------------------------------------------------
    async def _probe(
        self, credentials: dict[str, str], secrets: Iterable[str] = ()
    ) -> dict:
        """Call Zalo's ``getoa`` with the effective token.

        Returns ``{ok, oa_id, name, error}`` — never a credential. Zalo's error
        text can echo any of the four submitted values back, so ``secrets``
        carries every credential in play (posted, stored, and rotated) and is
        applied to both the provider's error text and the exception text, which
        must never reach ``oa_last_error`` unredacted.
        """
        from app.services.zalo_oa_service import ZaloOASender

        settings = self._settings
        if settings is None:
            from app.core.config import get_settings

            settings = get_settings()
        sender = ZaloOASender(
            settings=settings, access_token=credentials["zalo_oa_access_token"]
        )
        try:
            result = await sender.get_oa_info()
        except Exception as exc:  # noqa: BLE001 - a probe failure is a status, not a crash
            logger.warning("tingting oa probe failed error_type=%s", type(exc).__name__)
            return {"ok": False, "oa_id": "", "name": "", "error": _redact(str(exc), secrets)}
        if not result.ok:
            return {
                "ok": False,
                "oa_id": "",
                "name": "",
                "error": _redact(str(result.error or ""), secrets),
            }
        data = (result.raw or {}).get("data") if isinstance(result.raw, dict) else {}
        data = data if isinstance(data, dict) else {}
        oa_id = str(data.get("oa_id") or "").strip()
        name = str(data.get("name") or "").strip()
        if not oa_id:
            return {
                "ok": False,
                "oa_id": "",
                "name": "",
                "error": "Zalo không trả về mã OA (getoa)",
            }
        try:
            from app.channels.providers.zalo_account import validate_oa_id

            oa_id = validate_oa_id(oa_id)
        except Exception:  # noqa: BLE001 - a malformed id is a failed probe
            return {
                "ok": False,
                "oa_id": "",
                "name": "",
                "error": "Zalo trả về mã OA không hợp lệ",
            }
        return {"ok": True, "oa_id": oa_id, "name": name, "error": ""}

    async def _bump_cache(self) -> None:
        from app.core.cache import bump_cache_version
        from app.core.preamble_cache import NS_INTEGRATION_ZALO, evict_local_namespace

        evict_local_namespace(NS_INTEGRATION_ZALO)
        try:
            await bump_cache_version(NS_INTEGRATION_ZALO)
        except Exception:  # noqa: BLE001
            logger.warning("zalo cache version bump failed", exc_info=True)


__all__ = [
    "TINGTING_OA_ACCOUNT_KEY",
    "TINGTING_OA_CREDENTIAL_BASES",
    "TINGTING_OA_DEFAULT_LABEL",
    "TingtingOaLinkError",
    "TingtingOaLinkService",
    "processing_enabled",
]
