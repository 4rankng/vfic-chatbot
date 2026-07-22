"""Compatibility imports for outbound contracts now owned by ``app.shared``."""

from app.shared.application.outbound import (
    OutboundResult,
    OutboundTelemetry,
    combine_outbound_telemetry,
)

__all__ = ["OutboundResult", "OutboundTelemetry", "combine_outbound_telemetry"]
