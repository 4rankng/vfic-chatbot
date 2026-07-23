"""Pure forward-only delivery-state policy."""

from __future__ import annotations

from enum import Enum

_DELIVERY_RANK = {
    "PENDING": 0,
    "SENDING": 0,
    "SEND_UNKNOWN": 0,
    "FAILED": 0,
    "SUPPRESSED": 0,
    "SENT": 1,
    "DELIVERED": 2,
    "READ": 3,
}


def delivery_rank(status: str | Enum | None) -> int:
    value = status.value if isinstance(status, Enum) else status
    return _DELIVERY_RANK.get(str(value), 0) if value is not None else 0


def receipt_advances(current: str | Enum | None, target: str | Enum) -> bool:
    return delivery_rank(current) < delivery_rank(target)


__all__ = ["delivery_rank", "receipt_advances"]
