"""HTTP transport exception classification owned by the channel adapter edge."""

from __future__ import annotations

import httpx

from app.shared.application.outbound import OutboundErrorClass


def classify_transport_error(exc: BaseException) -> OutboundErrorClass:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "connect_error"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.RemoteProtocolError):
        return "remote_protocol_error"
    if isinstance(exc, httpx.ReadError):
        return "read_error"
    return "unknown"


__all__ = ["classify_transport_error"]
