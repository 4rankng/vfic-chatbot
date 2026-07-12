"""Transport-error classification for the SEND_UNKNOWN vs FAILED decision.

The graph layer owns the retryability decision: when a Zalo send raises a
transport exception, the runner must decide whether to mark the message
``SEND_UNKNOWN`` (non-retriable — the request may have reached Zalo) or
``FAILED`` (retryable — the request definitely did not reach Zalo).

This module is a leaf utility with NO service dependencies, so the services
layer can import it (``services → graph`` is the allowed direction) without
re-introducing the graph<->services cycle guarded by
``tests/test_graph_import_guard.py``.

Conservative classifier (validated): anything that could have reached Zalo
before failing is treated as SEND_UNKNOWN (at-most-once bias — a stuck message
is recoverable by a manual resend; a duplicate reply is not). Only definite
pre-send connection failures stay retryable (FAILED).
"""
from __future__ import annotations

import httpx


def classify_transport_error(exc: BaseException) -> str:
    """Map a transport exception to an error_class key for SEND_UNKNOWN routing.

    Returns one of:
      - ``connect_error``         → FAILED  (pre-send; retryable)
      - ``read_timeout``          → SEND_UNKNOWN (request written, no response)
      - ``remote_protocol_error`` → SEND_UNKNOWN (server closed mid-stream)
      - ``read_error``            → SEND_UNKNOWN (response interrupted after bytes sent)
      - ``unknown``               → SEND_UNKNOWN (conservative default)
    """
    # Definite pre-send failure: the connection was never established, so the
    # request definitely did not reach Zalo. Retryable.
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "connect_error"
    # Post-send ambiguity: the request was written but we got no / partial
    # response. Zalo may have accepted the message. Non-retriable.
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.RemoteProtocolError):
        return "remote_protocol_error"
    if isinstance(exc, httpx.ReadError):
        return "read_error"
    # Conservative default: treat any unrecognized transport failure as ambiguous
    # so the reconciler does not risk a duplicate reply.
    return "unknown"


# Error classes that indicate the request MAY have reached Zalo. The runner
# routes these to DeliveryStatus.SEND_UNKNOWN (non-retriable).
AMBIGUOUS_SEND_CLASSES = frozenset(
    {"read_timeout", "remote_protocol_error", "read_error", "unknown"}
)


def delivery_status_for_send_error(error_class: str | None, ok: bool):
    """Return the DeliveryStatus override for a failed send, or None if FAILED.

    Conservative: when ``ok`` is False and ``error_class`` is in
    ``AMBIGUOUS_SEND_CLASSES``, return ``DeliveryStatus.SEND_UNKNOWN`` (non-
    retriable — the request may have reached Zalo). Otherwise return None so
    the caller falls back to the default FAILED (retryable).

    Late import of DeliveryStatus avoids a model import at module top level
    (the graph layer imports ports, not models).
    """
    if ok or error_class not in AMBIGUOUS_SEND_CLASSES:
        return None
    from app.models.conversation import DeliveryStatus
    return DeliveryStatus.SEND_UNKNOWN
