"""The TingTing employee-support Zalo OA: verification state and serving.

One channel account (`zalo_oa` / ``tingting``). Payroll solely owns and rotates
the account's Zalo token pair (owner ruling 2026-10-07): it pushes the fresh
access token to ``POST /webhooks/zalo-oa-token`` after each rotation and at its
own startup, and serves ``GET /api/v1/integration/zalo/token`` as the pull
fallback the OA refresh path uses. The admin never supplies an App ID, Secret,
Access Token, or Refresh Token for this account, and this app never refreshes
it against Zalo OAuth.

What the admin (or history) configured before that handover still stands: the
OA's own id and display name live in the channel account's
``provider_metadata`` — discovered once by Zalo's ``getoa`` at link time. The
discovered id is what inbound routing matches (``ZaloOaAccountResolver``) and
what the reset-flow gate pins, so the flow runs on this OA and nowhere else.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import types as ct
from app.channels.types import TINGTING_OA_ACCOUNT_KEY
from app.models.channel_account import ChannelAccount

logger = logging.getLogger(__name__)


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
    """Read the support OA's verification state for routing and the reset gate.

    The name is historical: the link flow itself is gone — payroll owns the
    credentials, so there is nothing left to paste, probe, or rotate. What
    remains is the read side the routing and the reset flow depend on.
    """

    def __init__(self, db: AsyncSession, *, settings=None, cipher=None) -> None:
        self.db = db
        self._settings = settings
        self._cipher = cipher

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
        """Admin card projection: link state + the payroll-owned token's age.

        No credential status appears here — the four Zalo credentials are not
        admin inputs for this account any more. The token's last update and
        the fixed ownership note are the whole credential story the console
        renders.
        """
        settings_service = self._settings_service()
        row = await self._account()
        metadata = await self._metadata()
        return {
            "oa_linked": bool(row is not None and row.is_active and metadata.get("oa_id")),
            "oa_id": str(metadata.get("oa_id") or ""),
            "oa_name": str(metadata.get("name") or ""),
            "oa_label": (row.label if row is not None else "") or "",
            "oa_verified_at": metadata.get("verified_at"),
            "oa_last_checked_at": metadata.get("last_checked_at"),
            "oa_last_error": metadata.get("last_error") or "",
            "oa_token_updated_at": await settings_service.oa_account_token_updated_at(
                TINGTING_OA_ACCOUNT_KEY
            ),
            "oa_token_managed_note": TINGTING_OA_TOKEN_MANAGED_NOTE,
        }


# The fixed console label: this account's token is not an admin credential.
TINGTING_OA_TOKEN_MANAGED_NOTE = "Payroll quản lý và tự gia hạn token Zalo OA"


__all__ = [
    "TINGTING_OA_ACCOUNT_KEY",
    "TINGTING_OA_TOKEN_MANAGED_NOTE",
    "TingtingOaLinkService",
    "processing_enabled",
]
