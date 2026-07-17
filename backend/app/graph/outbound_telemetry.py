"""Channel-neutral metrics for one outbound adapter operation.

The bot graph records these values in ``BotRun.stage_timings``. The contract is
intentionally independent of a channel vendor: future Facebook, Telegram, or
WhatsApp adapters can attach the same value to their send result without adding
adapter-specific branches to the graph runner.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

OutboundResult = Literal["sent", "rejected", "transport_error", "provider_error"]


@dataclass(frozen=True)
class OutboundTelemetry:
    """Safe, additive timing data for a completed outbound send.

    All durations are milliseconds. This model deliberately excludes message
    bodies, recipient identifiers, credential values, and provider envelopes.
    """

    adapter: str
    adapter_prepare_ms: int = 0
    provider_request_ms: int = 0
    provider_attempts: int = 0
    retry_count: int = 0
    retry_ms: int = 0
    refresh_count: int = 0
    refresh_ms: int = 0
    chunk_count: int = 0
    result: OutboundResult = "provider_error"

    def with_result(self, result: OutboundResult) -> "OutboundTelemetry":
        return replace(self, result=result)

    def to_stage_timings(self) -> dict[str, int | str]:
        """Flatten to JSON-safe keys so PostgreSQL dashboard rollups stay simple."""
        return {
            "outbound_adapter": self.adapter,
            "outbound_prepare_ms": self.adapter_prepare_ms,
            "outbound_provider_ms": self.provider_request_ms,
            "outbound_provider_attempts": self.provider_attempts,
            "outbound_retry_count": self.retry_count,
            "outbound_retry_ms": self.retry_ms,
            "outbound_refresh_count": self.refresh_count,
            "outbound_refresh_ms": self.refresh_ms,
            "outbound_chunk_count": self.chunk_count,
            "outbound_result": self.result,
        }


def combine_outbound_telemetry(
    base: OutboundTelemetry, chunks: list[OutboundTelemetry], *, result: OutboundResult
) -> OutboundTelemetry:
    """Aggregate a potentially chunked send without exposing chunk payloads."""
    return OutboundTelemetry(
        adapter=base.adapter,
        adapter_prepare_ms=base.adapter_prepare_ms,
        provider_request_ms=sum(chunk.provider_request_ms for chunk in chunks),
        provider_attempts=sum(chunk.provider_attempts for chunk in chunks),
        retry_count=sum(chunk.retry_count for chunk in chunks),
        retry_ms=sum(chunk.retry_ms for chunk in chunks),
        refresh_count=sum(chunk.refresh_count for chunk in chunks),
        refresh_ms=sum(chunk.refresh_ms for chunk in chunks),
        chunk_count=len(chunks),
        result=result,
    )
