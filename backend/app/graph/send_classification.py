"""Compatibility facade for outbound classification during the DDD migration."""

from app.channels.http_error_classification import classify_transport_error
from app.conversation_messaging.domain.delivery import DeliveryState
from app.shared.application.outbound import AMBIGUOUS_SEND_CLASSES, is_ambiguous_send


def delivery_status_for_send_error(error_class: str | None, ok: bool):
    if not is_ambiguous_send(error_class, ok=ok):
        return None
    return DeliveryState.SEND_UNKNOWN


__all__ = [
    "AMBIGUOUS_SEND_CLASSES",
    "classify_transport_error",
    "delivery_status_for_send_error",
]
