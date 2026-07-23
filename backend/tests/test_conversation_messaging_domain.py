from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.conversation_messaging.domain.delivery import delivery_rank, receipt_advances
from app.conversation_messaging.domain.ownership import (
    lock_owner_matches,
    lock_still_live,
    normalize_lock_owner,
)


def test_lock_owner_policy_accepts_legacy_unowned_guard_and_exact_owner() -> None:
    owner = uuid.uuid4()

    assert normalize_lock_owner(str(owner)) == owner
    assert lock_owner_matches(uuid.uuid4(), None)
    assert lock_owner_matches(owner, str(owner))
    assert not lock_owner_matches(None, owner)
    assert not lock_owner_matches(uuid.uuid4(), owner)


def test_lock_owner_policy_rejects_invalid_uuid() -> None:
    with pytest.raises(ValueError):
        normalize_lock_owner("not-a-uuid")


def test_lock_liveness_handles_naive_and_aware_timestamps() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)

    assert lock_still_live(now + timedelta(seconds=1), now=now)
    assert lock_still_live((now + timedelta(seconds=1)).replace(tzinfo=None), now=now)
    assert not lock_still_live(now, now=now)
    assert not lock_still_live(None, now=now)


def test_delivery_receipts_progress_forward_only() -> None:
    assert delivery_rank("PENDING") == 0
    assert delivery_rank("SENT") == 1
    assert delivery_rank("DELIVERED") == 2
    assert delivery_rank("READ") == 3
    assert receipt_advances("SENT", "DELIVERED")
    assert receipt_advances("DELIVERED", "READ")
    assert not receipt_advances("READ", "DELIVERED")
    assert not receipt_advances("SEND_UNKNOWN", "UNKNOWN")
