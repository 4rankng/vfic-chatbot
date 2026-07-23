"""Persistence enum adapter for neutral delivery-status values."""

from __future__ import annotations

from app.models.conversation import DeliveryStatus


class SqlAlchemyDeliveryStatusValues:
    @property
    def suppressed(self) -> DeliveryStatus:
        return DeliveryStatus.SUPPRESSED

    @property
    def send_unknown(self) -> DeliveryStatus:
        return DeliveryStatus.SEND_UNKNOWN


__all__ = ["SqlAlchemyDeliveryStatusValues"]
