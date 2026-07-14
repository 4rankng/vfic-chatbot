"""Job mutations invalidate cached candidate recommendations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.job_service import JobService


@pytest.mark.asyncio
async def test_update_bumps_jobs_cache_version(monkeypatch):
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    bumped: list[str] = []

    async def _bump(namespace: str) -> None:
        bumped.append(namespace)

    monkeypatch.setattr("app.services.job_service.bump_cache_version", _bump)
    job = SimpleNamespace(status="ACTIVE", vacancy_count=2)

    updated = await JobService(db).update(job, {"status": "FULL", "vacancy_count": 0})

    assert updated is job
    assert job.status == "FULL"
    assert job.vacancy_count == 0
    assert bumped == ["jobs"]
