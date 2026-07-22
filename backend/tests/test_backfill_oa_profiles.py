from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from scripts import backfill_oa_profiles as backfill


def test_parse_args_requires_mode_and_nonnegative_values() -> None:
    assert backfill._parse_args(["--dry-run"]).dry_run is True
    assert backfill._parse_args(["--apply", "--limit", "0"]).limit == 0
    with pytest.raises(SystemExit):
        backfill._parse_args(["--apply", "--limit", "-1"])


@pytest.mark.asyncio
async def test_dry_run_reports_aggregate_without_provider_calls(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_session():
        yield object()

    async def eligible(_db, *, limit):
        return [backfill.EligibleProfile("oa:one"), backfill.EligibleProfile("oa:two")]

    monkeypatch.setattr(backfill, "async_session", fake_session)
    monkeypatch.setattr(backfill, "_eligible_profiles", eligible)
    monkeypatch.setattr(backfill, "_enrich_one", lambda _id: pytest.fail("unexpected call"))
    assert await backfill._run(backfill._parse_args(["--dry-run"])) == {
        "dry_run": True,
        "eligible": 2,
        "attempted": 0,
        "enriched": 0,
        "unchanged": 0,
        "failed": 0,
    }


@pytest.mark.asyncio
async def test_apply_processes_all_rows_and_continues_after_failure(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_session():
        yield object()

    async def eligible(_db, *, limit):
        return [
            backfill.EligibleProfile("oa:first"),
            backfill.EligibleProfile("oa:second"),
            backfill.EligibleProfile("oa:third"),
        ]

    attempts = []

    async def enrich(zalo_id):
        attempts.append(zalo_id)
        if zalo_id == "oa:second":
            raise TimeoutError
        return zalo_id == "oa:first"

    monkeypatch.setattr(backfill, "async_session", fake_session)
    monkeypatch.setattr(backfill, "_eligible_profiles", eligible)
    monkeypatch.setattr(backfill, "_enrich_one", enrich)
    report = await backfill._run(backfill._parse_args(["--apply", "--delay-seconds", "0"]))
    assert attempts == ["oa:first", "oa:second", "oa:third"]
    assert report == {
        "dry_run": False,
        "eligible": 3,
        "attempted": 3,
        "enriched": 1,
        "unchanged": 1,
        "failed": 1,
    }
