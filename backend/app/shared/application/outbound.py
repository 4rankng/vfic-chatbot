"""Immutable provider-neutral outbound result and telemetry contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

OutboundResult = Literal["sent", "rejected", "transport_error", "provider_error"]
OutboundErrorClass = Literal[
    "connect_error",
    "read_timeout",
    "remote_protocol_error",
    "read_error",
    "unknown",
    "provider_error",
    "policy_suppressed",
    "auth_revoked",
]

AMBIGUOUS_SEND_CLASSES: frozenset[OutboundErrorClass] = frozenset(
    {"read_timeout", "remote_protocol_error", "read_error", "unknown"}
)


def is_ambiguous_send(error_class: str | None, *, ok: bool) -> bool:
    """Return whether a failed provider request may already have been accepted."""
    return not ok and error_class in AMBIGUOUS_SEND_CLASSES


@dataclass(frozen=True)
class OutboundTelemetry:
    """Safe timing data for one outbound operation; contains no payload or IDs."""

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
    base: OutboundTelemetry,
    chunks: list[OutboundTelemetry],
    *,
    result: OutboundResult,
) -> OutboundTelemetry:
    """Aggregate chunk timings without retaining any chunk payload."""
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


__all__ = [
    "AMBIGUOUS_SEND_CLASSES",
    "OutboundErrorClass",
    "OutboundResult",
    "OutboundTelemetry",
    "combine_outbound_telemetry",
    "is_ambiguous_send",
]
