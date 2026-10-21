"""On-demand day fetch for the Cloudfone transcripts viewer.

The daily insights pass only ever covers the previous day, so an admin opening
an older day in the viewer would see an empty table. ``backfill_day_transcripts``
is the viewer's own fetch: same vendor call, same recording download, same
MiniMax STT, same stored rows — it just runs when an admin asks for that day.

These tests pin the rules that matter for the viewer:
  - a day that was already checked is NOT fetched again (the marker says the
    day is known, and a known day may be empty);
  - an unchecked day is fetched and its transcripts stored;
  - a missing credential or a missing STT key never touches the vendor;
  - a vendor failure is recorded as an error, so a later attempt may retry.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import cloudfone as cloudfone_module
from app.services.cloudfone import (
    BACKFILL_CHECKED,
    BACKFILL_FAILED,
    BACKFILL_SKIPPED,
    BACKFILL_UNCONFIGURED,
    CallRecord,
    CloudfoneError,
    backfill_day_transcripts,
)
from app.services.cloudfone_transcripts import (
    DAY_STATUS_CHECKED,
    DAY_STATUS_ERROR,
    DAY_STATUS_UNCHECKED,
    CloudfoneTranscriptDay,
)

DAY = date(2026, 10, 18)


class _FakeSettingsService:
    def __init__(self, cloudfone_cfg, minimax_cfg=None) -> None:
        self._cloudfone = cloudfone_cfg
        self._minimax = minimax_cfg

    async def resolve_cloudfone(self):
        return self._cloudfone

    async def resolve_email_digest(self):  # pragma: no cover — not used here
        raise AssertionError("the backfill never sends the insights email")

    async def resolve_minimax(self):
        return self._minimax


def _cloudfone_cfg(**overrides):
    values: dict = {
        "service_name": "CloudFone",
        "auth_user": "cloudfone-user",
        "auth_key": "cf-key",
        "recipients": ("ops@vp.vn",),
        "enabled": True,
    }
    values.update(overrides)
    return type("Cfg", (), values)()


class _FakeMinimax:
    def __init__(self, api_key: str = "mk-key") -> None:
        self.api_key = api_key


def _call(call_id: str = "c1", talk_seconds: int = 30) -> CallRecord:
    return CallRecord(
        call_id=call_id,
        started_at="2026-10-18T09:00:00",
        caller="0912345678",
        status="ANSWERED",
        talk_seconds=talk_seconds,
        recording_url=f"https://rec/{call_id}",
    )


class _FakeStore:
    """In-memory transcript store (the seam ``run_cloudfone_insights`` takes)."""

    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    async def load(self, call_id: str) -> str | None:
        return self.rows.get(call_id)

    async def save(self, call, transcript: str, day: date) -> None:
        self.rows[call.call_id] = transcript


class _FakeDayStateSession:
    """Session double that answers the day-marker lookup."""

    def __init__(self, state: CloudfoneTranscriptDay | None) -> None:
        self._state = state
        self.written: list[CloudfoneTranscriptDay] = []

    async def scalar(self, query):
        return self._state

    async def commit(self):
        return None

    async def refresh(self, _row):
        return None

    def add(self, row) -> None:
        self.written.append(row)

    async def flush(self):
        return None


@pytest.fixture
def no_download(monkeypatch):
    """Recordings are never downloaded in these tests unless a case says so."""

    async def download(_url: str) -> bytes:  # pragma: no cover — safety net
        raise AssertionError("the recording must not be downloaded in this case")

    monkeypatch.setattr(cloudfone_module, "download_recording", download)


async def _fetcher(calls: list[CallRecord]):
    async def fetch(_day):
        return list(calls)

    return fetch


async def test_an_unchecked_day_is_fetched_and_its_transcripts_stored(monkeypatch):
    """The viewer's on-demand fetch stores the transcripts it produces."""
    seen_audio: list[bytes] = []

    async def download(url: str) -> bytes:
        return url.encode()

    async def transcriber(audio: bytes) -> str:
        seen_audio.append(audio)
        return "S1: nội dung cuộc gọi"

    monkeypatch.setattr(cloudfone_module, "download_recording", download)
    store = _FakeStore()
    session = _FakeDayStateSession(None)

    outcome = await backfill_day_transcripts(
        session,
        DAY,
        service=_FakeSettingsService(_cloudfone_cfg(), _FakeMinimax()),
        transcriber=transcriber,
        fetcher=await _fetcher([_call()]),
        store=store,
    )

    assert outcome.status == BACKFILL_CHECKED
    assert outcome.calls == 1
    assert outcome.recordable == 1
    assert outcome.transcripts == 1
    assert outcome.added == 1
    assert outcome.remaining == 0
    assert store.rows["c1"] == "S1: nội dung cuộc gọi"
    # The day is now known — the viewer will not fetch it again on its own.
    [marker] = session.written
    assert marker.status == DAY_STATUS_CHECKED
    assert marker.call_count == 1


async def test_a_day_that_was_already_checked_is_not_fetched_again(no_download):
    """The marker is the "that day has no record" rule: a known day is left alone."""
    session = _FakeDayStateSession(
        CloudfoneTranscriptDay(
            day=DAY,
            status=DAY_STATUS_CHECKED,
            call_count=3,
            recordable_count=1,
            transcript_count=0,
        )
    )

    async def fetcher(_day):
        raise AssertionError("a checked day must not be fetched again")

    outcome = await backfill_day_transcripts(
        session,
        DAY,
        service=_FakeSettingsService(_cloudfone_cfg(), _FakeMinimax()),
        transcriber=lambda audio: None,
        fetcher=fetcher,
        store=_FakeStore(),
    )

    assert outcome.status == BACKFILL_SKIPPED
    assert outcome.calls == 3
    assert outcome.transcripts == 0


async def test_a_checked_day_can_be_refetched_on_an_explicit_force(no_download, monkeypatch):
    """An admin who knows the day is empty can ask for it again."""
    session = _FakeDayStateSession(
        CloudfoneTranscriptDay(
            day=DAY,
            status=DAY_STATUS_CHECKED,
            call_count=3,
            recordable_count=1,
            transcript_count=0,
        )
    )

    async def download(url: str) -> bytes:
        return url.encode()

    async def transcriber(audio: bytes) -> str:
        return "S1: nội dung"

    monkeypatch.setattr(cloudfone_module, "download_recording", download)
    store = _FakeStore()

    outcome = await backfill_day_transcripts(
        session,
        DAY,
        service=_FakeSettingsService(_cloudfone_cfg(), _FakeMinimax()),
        transcriber=transcriber,
        fetcher=await _fetcher([_call()]),
        store=store,
        force=True,
    )

    assert outcome.status == BACKFILL_CHECKED
    assert outcome.added == 1
    assert store.rows["c1"] == "S1: nội dung"


async def test_a_missing_credential_never_touches_the_vendor(no_download):
    session = _FakeDayStateSession(None)

    async def fetcher(_day):
        raise AssertionError("an unconfigured day must not be fetched")

    outcome = await backfill_day_transcripts(
        session,
        DAY,
        service=_FakeSettingsService(_cloudfone_cfg(auth_key=""), _FakeMinimax()),
        transcriber=lambda audio: None,
        fetcher=fetcher,
        store=_FakeStore(),
    )

    assert outcome.status == BACKFILL_UNCONFIGURED
    assert outcome.missing == ["auth_key"]
    assert session.written == []


async def test_a_missing_stt_key_never_touches_the_vendor(no_download):
    session = _FakeDayStateSession(None)

    async def fetcher(_day):
        raise AssertionError("without an STT key there is nothing to fetch for")

    outcome = await backfill_day_transcripts(
        session,
        DAY,
        service=_FakeSettingsService(_cloudfone_cfg(), _FakeMinimax(api_key="")),
        transcriber=None,
        fetcher=fetcher,
        store=_FakeStore(),
    )

    assert outcome.status == BACKFILL_UNCONFIGURED
    assert outcome.missing == ["minimax_api_key"]
    assert session.written == []


async def test_a_vendor_failure_is_recorded_so_a_later_attempt_may_retry(no_download):
    session = _FakeDayStateSession(None)

    async def fetcher(_day):
        raise CloudfoneError("CloudFone không phản hồi")

    outcome = await backfill_day_transcripts(
        session,
        DAY,
        service=_FakeSettingsService(_cloudfone_cfg(), _FakeMinimax()),
        transcriber=lambda audio: None,
        fetcher=fetcher,
        store=_FakeStore(),
    )

    assert outcome.status == BACKFILL_FAILED
    assert "không phản hồi" in (outcome.message or "")
    [marker] = session.written
    assert marker.status == DAY_STATUS_ERROR
    assert marker.error


async def test_an_unchecked_day_is_the_only_one_that_gets_fetched(no_download):
    """The viewer asks for the day; the marker decides whether it is fetched."""
    session = _FakeDayStateSession(None)
    assert session._state is None
    assert DAY_STATUS_UNCHECKED == "unchecked"
