"""Pure bot-turn ownership and lease policies."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def normalize_lock_owner(lock_owner: uuid.UUID | str | None) -> uuid.UUID | None:
    if lock_owner is None:
        return None
    if isinstance(lock_owner, uuid.UUID):
        return lock_owner
    return uuid.UUID(str(lock_owner))


def lock_owner_matches(
    current: uuid.UUID | str | None,
    expected: uuid.UUID | str | None,
) -> bool:
    expected_owner = normalize_lock_owner(expected)
    if expected_owner is None:
        return True
    if current is None:
        return False
    return str(current) == str(expected_owner)


def lock_still_live(
    locked_until: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    if locked_until is None:
        return False
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return locked_until > instant


__all__ = ["lock_owner_matches", "lock_still_live", "normalize_lock_owner"]
