"""Service adapter for the current Zalo ingress transaction."""

from __future__ import annotations

from typing import Any

from app.services.webhook import ZaloWebhookService


class ServiceZaloIngressAdapter:
    def __init__(self, db) -> None:
        self._db = db

    async def handle(
        self,
        payload: dict[str, Any],
        *,
        enqueue,
        channel: str,
        bot_token: str | None,
        runtime_authority: object | None,
        enrich_oa_profile,
    ) -> dict[str, Any]:
        return await ZaloWebhookService.handle(
            self._db,
            payload,
            enqueue=enqueue,
            channel=channel,
            bot_token=bot_token,
            runtime_authority=runtime_authority,
            enrich_oa_profile=enrich_oa_profile,
        )


__all__ = ["ServiceZaloIngressAdapter"]
