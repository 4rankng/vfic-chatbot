from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from scripts import backfill_oa_profiles as backfill


@pytest.fixture(autouse=True)
def _lookup_not_terminated(monkeypatch) -> None:
    """Default: no identity carries the terminal unreachable marker."""

    async def not_terminated(_external_id, **_kwargs):
        return False

    monkeypatch.setattr(backfill, "is_profile_lookup_terminated", not_terminated)


@pytest.mark.asyncio
async def test_enrich_one_forces_db_eligible_profile_lookup(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_session():
        yield object()

    class FakeSettings:
        def __init__(self, _db) -> None:
            pass

        async def resolve_zalo(self, account_key=None):
            return SimpleNamespace(oa_access_token="test-token")

        async def refresh_oa_access_token(self, account_key=None):
            return "refreshed"

    class FakeSender:
        def __init__(self, *, access_token, refresh) -> None:
            assert access_token == "test-token"
            assert refresh is not None

    captured: dict[str, object] = {}

    class FakeEnrichment:
        def __init__(self, _db, _sender) -> None:
            pass

        async def enrich_oa_user(self, zalo_id, **kwargs):
            captured.update(zalo_id=zalo_id, **kwargs)
            return True

    monkeypatch.setattr(backfill, "async_session", fake_session)
    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService", FakeSettings
    )
    monkeypatch.setattr("app.services.zalo_oa_service.ZaloOASender", FakeSender)
    monkeypatch.setattr(
        "app.services.profile_enrichment.ProfileEnrichmentService", FakeEnrichment
    )

    assert await backfill._enrich_one("oa:private-user") is True
    assert captured == {
        "zalo_id": "oa:private-user",
        "user_id": "private-user",
        "wait_for_inflight": True,
        "force_lookup": True,
    }


def test_parse_args_defaults_to_bounded_pages_and_retries() -> None:
    args = backfill._parse_args(["--apply"])
    assert args.limit == 0
    assert args.batch_size == 50
    assert args.max_attempts == 3
    with pytest.raises(SystemExit):
        backfill._parse_args(["--apply", "--batch-size", "0"])


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        ({"lock_acquired": True, "failed": 0, "limit_reached": False, "remaining": 0}, 0),
        ({"lock_acquired": True, "failed": 1, "limit_reached": False, "remaining": 1}, 2),
        ({"lock_acquired": True, "failed": 0, "limit_reached": False, "remaining": 1}, 2),
        ({"lock_acquired": True, "failed": 0, "limit_reached": True, "remaining": 4}, 0),
        ({"lock_acquired": False, "failed": 0, "limit_reached": False, "remaining": 4}, 3),
    ],
)
def test_exit_codes_describe_completion_state(report, expected) -> None:
    assert backfill._exit_code(backfill._parse_args(["--apply"]), report) == expected
    assert backfill._exit_code(backfill._parse_args(["--dry-run"]), report) == 0


@pytest.mark.asyncio
async def test_process_profile_retries_until_db_checkpoint_is_complete(monkeypatch) -> None:
    attempts = 0
    missing = iter([True, False])
    sleeps: list[float] = []

    async def enrich(_zalo_id):
        nonlocal attempts
        attempts += 1
        return attempts == 2

    async def still_missing(_zalo_id):
        return next(missing)

    async def sleep(value):
        sleeps.append(value)

    monkeypatch.setattr(backfill, "_enrich_one", enrich)
    monkeypatch.setattr(backfill, "_profile_still_missing", still_missing)
    monkeypatch.setattr(backfill.asyncio, "sleep", sleep)
    assert await backfill._process_profile(
        "oa:private-user", max_attempts=3, retry_delay_seconds=1
    ) == ("complete", True)
    assert attempts == 2
    assert sleeps == [1]


@pytest.mark.asyncio
async def test_process_profile_reports_incomplete_after_bounded_attempts(monkeypatch) -> None:
    attempts = 0

    async def enrich(_zalo_id):
        nonlocal attempts
        attempts += 1
        return False

    async def still_missing(_zalo_id):
        return True

    async def no_sleep(_value):
        return None

    monkeypatch.setattr(backfill, "_enrich_one", enrich)
    monkeypatch.setattr(backfill, "_profile_still_missing", still_missing)
    monkeypatch.setattr(backfill.asyncio, "sleep", no_sleep)
    assert await backfill._process_profile(
        "oa:private-user", max_attempts=3, retry_delay_seconds=1
    ) == ("failed", False)
    assert attempts == 3


@pytest.mark.asyncio
async def test_process_profile_retries_transient_checkpoint_failures(monkeypatch) -> None:
    checks = 0

    async def enrich(_zalo_id):
        return True

    async def still_missing(_zalo_id):
        nonlocal checks
        checks += 1
        if checks == 1:
            raise ConnectionError("temporary database failure")
        return False

    async def no_sleep(_value):
        return None

    monkeypatch.setattr(backfill, "_enrich_one", enrich)
    monkeypatch.setattr(backfill, "_profile_still_missing", still_missing)
    monkeypatch.setattr(backfill.asyncio, "sleep", no_sleep)

    assert await backfill._process_profile(
        "oa:private-user", max_attempts=3, retry_delay_seconds=1
    ) == ("complete", True)
    assert checks == 2


@pytest.mark.asyncio
async def test_process_profile_stops_when_lookup_is_terminated(monkeypatch) -> None:
    attempts = 0

    async def enrich(_zalo_id):
        nonlocal attempts
        attempts += 1
        return False

    async def still_missing(_zalo_id):
        return True

    async def no_sleep(_value):
        return None

    async def terminated(_external_id, **_kwargs):
        return True

    monkeypatch.setattr(backfill, "_enrich_one", enrich)
    monkeypatch.setattr(backfill, "_profile_still_missing", still_missing)
    monkeypatch.setattr(backfill.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(backfill, "is_profile_lookup_terminated", terminated)

    assert await backfill._process_profile(
        "oa:private-user", max_attempts=3, retry_delay_seconds=1
    ) == ("unreachable", False)
    assert attempts == 1


@pytest.mark.asyncio
async def test_run_pages_all_rows_and_emits_no_profile_identifiers(monkeypatch, capsys) -> None:
    @asynccontextmanager
    async def fake_session():
        yield object()

    @asynccontextmanager
    async def fake_lock():
        yield True

    counts = iter([3, 0])
    page_calls: list[tuple[str | None, int]] = []

    async def eligible_count(_db):
        return next(counts)

    async def page(_db, *, after, batch_size):
        page_calls.append((after, batch_size))
        if after is None:
            return [backfill.EligibleProfile("oa:secret-one"), backfill.EligibleProfile("oa:secret-two")]
        if after == "oa:secret-two":
            return [backfill.EligibleProfile("oa:secret-three")]
        return []

    async def process(_zalo_id, **_kwargs):
        return "complete", True

    async def eligible_remaining(_db, *, batch_size):
        return 0

    monkeypatch.setattr(backfill, "async_session", fake_session)
    monkeypatch.setattr(backfill, "_exclusive_backfill", fake_lock)
    monkeypatch.setattr(backfill, "_eligible_count", eligible_count)
    monkeypatch.setattr(backfill, "_eligible_profiles_page", page)
    monkeypatch.setattr(backfill, "_process_profile", process)
    monkeypatch.setattr(backfill, "_eligible_remaining", eligible_remaining)

    args = backfill._parse_args(["--apply", "--batch-size", "2", "--delay-seconds", "0"])
    report = await backfill._run(args)
    assert report["attempted"] == 3
    assert report["completed"] == 3
    assert report["remaining"] == 0
    assert page_calls == [(None, 2), ("oa:secret-two", 2), ("oa:secret-three", 2)]
    output = capsys.readouterr().out
    assert "secret-one" not in output
    assert '"event": "batch"' in output
    assert '"event": "final"' in output


@pytest.mark.asyncio
async def test_run_reports_lock_contention_without_processing(monkeypatch, capsys) -> None:
    @asynccontextmanager
    async def fake_session():
        yield object()

    @asynccontextmanager
    async def busy_lock():
        yield False

    async def eligible_count(_db):
        return 4

    monkeypatch.setattr(backfill, "async_session", fake_session)
    monkeypatch.setattr(backfill, "_exclusive_backfill", busy_lock)
    monkeypatch.setattr(backfill, "_eligible_count", eligible_count)
    report = await backfill._run(backfill._parse_args(["--apply"]))
    assert report["lock_acquired"] is False
    assert report["attempted"] == 0
    assert backfill._exit_code(backfill._parse_args(["--apply"]), report) == 3
    output = capsys.readouterr().out
    assert '"event": "locked"' in output
    assert '"event": "final"' in output


@pytest.mark.asyncio
async def test_run_skips_terminated_candidates_without_processing(
    monkeypatch, capsys
) -> None:
    @asynccontextmanager
    async def fake_session():
        yield object()

    @asynccontextmanager
    async def fake_lock():
        yield True

    async def eligible_count(_db):
        return 2

    async def page(_db, *, after, batch_size):
        if after is None:
            return [
                backfill.EligibleProfile("oa:secret-one"),
                backfill.EligibleProfile("oa:secret-two"),
            ]
        return []

    processed: list[str] = []

    async def process(zalo_id, **_kwargs):
        processed.append(zalo_id)
        return "complete", True

    terminated_ids = {"oa:secret-one"}

    async def terminated(external_id, **_kwargs):
        return external_id in terminated_ids

    async def eligible_remaining(_db, *, batch_size):
        return 0

    monkeypatch.setattr(backfill, "async_session", fake_session)
    monkeypatch.setattr(backfill, "_exclusive_backfill", fake_lock)
    monkeypatch.setattr(backfill, "_eligible_count", eligible_count)
    monkeypatch.setattr(backfill, "_eligible_profiles_page", page)
    monkeypatch.setattr(backfill, "_process_profile", process)
    monkeypatch.setattr(backfill, "is_profile_lookup_terminated", terminated)
    monkeypatch.setattr(backfill, "_eligible_remaining", eligible_remaining)

    report = await backfill._run(backfill._parse_args(["--apply", "--delay-seconds", "0"]))

    assert processed == ["oa:secret-two"]
    assert report["attempted"] == 2
    assert report["completed"] == 1
    assert report["unreachable"] == 1
    output = capsys.readouterr().out
    assert '"unreachable": 1' in output
    assert "secret-one" not in output


@pytest.mark.asyncio
async def test_eligible_remaining_excludes_terminated_identities(monkeypatch) -> None:
    async def page(_db, *, after, batch_size):
        if after is None:
            return [
                backfill.EligibleProfile("oa:secret-one"),
                backfill.EligibleProfile("oa:secret-two"),
            ]
        if after == "oa:secret-two":
            return [backfill.EligibleProfile("oa:secret-three")]
        return []

    terminated_ids = {"oa:secret-one", "oa:secret-three"}

    async def terminated(external_id, **_kwargs):
        return external_id in terminated_ids

    monkeypatch.setattr(backfill, "_eligible_profiles_page", page)
    monkeypatch.setattr(backfill, "is_profile_lookup_terminated", terminated)

    assert await backfill._eligible_remaining(object(), batch_size=2) == 1
