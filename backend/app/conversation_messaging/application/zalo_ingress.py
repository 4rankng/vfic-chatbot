"""Application entry point for the established Zalo ingress transaction."""

from __future__ import annotations

from typing import Any, Protocol


class ZaloIngressPort(Protocol):
    async def handle(
        self,
        payload: dict[str, Any],
        *,
        enqueue,
        channel: str,
        bot_token: str | None,
        runtime_authority: object | None,
        enrich_oa_profile,
    ) -> dict[str, Any]: ...


class ZaloIngressUseCases:
    """Keep HTTP transport independent of the compatibility service adapter."""

    def __init__(self, port: ZaloIngressPort) -> None:
        self._port = port

    async def handle(
        self,
        payload: dict[str, Any],
        *,
        enqueue,
        channel: str = "bot",
        bot_token: str | None = None,
        runtime_authority: object | None = None,
        enrich_oa_profile=None,
    ) -> dict[str, Any]:
        return await self._port.handle(
            payload,
            enqueue=enqueue,
            channel=channel,
            bot_token=bot_token,
            runtime_authority=runtime_authority,
            enrich_oa_profile=enrich_oa_profile,
        )


__all__ = ["ZaloIngressPort", "ZaloIngressUseCases"]
