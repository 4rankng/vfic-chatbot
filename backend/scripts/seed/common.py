"""Shared primitives for the dev seed fixtures.

Every fixture module takes its clock, its generated UUIDs, and its randomness
from here so the whole seed stays reproducible. ``rng`` is deliberately a
single process-wide instance: it is consumed in *call order*, so the sequence
in which :func:`scripts.seed.runner.seed` invokes the fixture modules is part of
the fixture contract, not an implementation detail.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)
rng = random.Random(42)  # deterministic seed for reproducibility


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


def hours_ago(n: float) -> datetime:
    return NOW - timedelta(hours=n)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
