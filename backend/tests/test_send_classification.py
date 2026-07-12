"""Unit tests for the transport-error classifier powering SEND_UNKNOWN routing.

Validates the conservative bias: anything that could have reached Zalo before
failing is treated as ambiguous (SEND_UNKNOWN); only definite pre-send
connection failures stay retryable (FAILED).
"""
from __future__ import annotations

import httpx

from app.graph.send_classification import (
    AMBIGUOUS_SEND_CLASSES,
    classify_transport_error,
)


def test_connect_error_is_retryable():
    """Pre-send connection failure → connect_error (FAILED, retryable)."""
    assert classify_transport_error(httpx.ConnectError("refused")) == "connect_error"
    assert classify_transport_error(httpx.ConnectTimeout("slow")) == "connect_error"


def test_read_timeout_is_ambiguous():
    """Request written, no response → read_timeout (SEND_UNKNOWN)."""
    assert classify_transport_error(httpx.ReadTimeout("no reply")) == "read_timeout"


def test_remote_protocol_error_is_ambiguous():
    assert classify_transport_error(
        httpx.RemoteProtocolError("server closed")
    ) == "remote_protocol_error"


def test_read_error_is_ambiguous():
    assert classify_transport_error(httpx.ReadError("interrupted")) == "read_error"


def test_unknown_exception_is_ambiguous_conservative():
    """Unrecognized transport failure → unknown (SEND_UNKNOWN, conservative)."""
    assert classify_transport_error(RuntimeError("weird")) == "unknown"
    assert classify_transport_error(ConnectionResetError("reset")) == "unknown"


def test_ambiguous_set_excludes_connect_error():
    """AMBIGUOUS_SEND_CLASSES must NOT include connect_error (that's retryable)."""
    assert "connect_error" not in AMBIGUOUS_SEND_CLASSES
    assert "read_timeout" in AMBIGUOUS_SEND_CLASSES
    assert "remote_protocol_error" in AMBIGUOUS_SEND_CLASSES
    assert "read_error" in AMBIGUOUS_SEND_CLASSES
    assert "unknown" in AMBIGUOUS_SEND_CLASSES
