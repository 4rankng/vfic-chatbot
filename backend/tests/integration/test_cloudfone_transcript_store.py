"""Real-DB tests for the Cloudfone transcript store.

The unit suite drives the ``TranscriptStore`` seam with fakes, so the SQLAlchemy
row mapping of migration 0076 shipped unexercised: a column mismatch between
model and migration would only surface in production, on the first daily tick.
These tests commit real rows against the disposable database so that drift is
caught here instead.

The per-day marker (migration 0077) is covered the same way — it is what tells
the admin viewer that a day was already fetched from the vendor.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.cloudfone import CallRecord
from app.services.cloudfone_transcripts import (
    DAY_STATUS_CHECKED,
    DAY_STATUS_ERROR,
    DbTranscriptStore,
    get_call_transcript,
    get_day_state,
    list_call_transcripts,
    record_day_state,
)

pytestmark = pytest.mark.integration


def _call(call_id: str = "1790848955") -> CallRecord:
    return CallRecord(
        call_id=call_id,
        started_at="2026-10-01T17:02:35",
        caller="0362698948",
        direction="inbound",
        talk_seconds=98,
        transcript="",
    )


async def test_saved_transcript_is_loadable(integration_session):
    store = DbTranscriptStore(integration_session)
    await store.save(_call(), "Alo ạ? Khách hỏi kết bạn.", date(2026, 10, 1))

    assert await store.load("1790848955") == "Alo ạ? Khách hỏi kết bạn."
    assert await store.load("khong-ton-tai") is None


async def test_call_id_is_unique(integration_session):
    store = DbTranscriptStore(integration_session)
    await store.save(_call(), "Lần một.", date(2026, 10, 1))

    with pytest.raises(IntegrityError):
        await store.save(_call(), "Lần hai.", date(2026, 10, 1))

    # save() rolled the failed write back: the session stays usable and can
    # keep storing other calls (each save is its own committed transaction in
    # production, so earlier rows are durable there regardless).
    await store.save(_call("1790848956"), "Cuộc khác.", date(2026, 10, 1))
    assert await store.load("1790848956") == "Cuộc khác."


async def _seed(store: DbTranscriptStore, rows: list[tuple[CallRecord, str, date]]) -> None:
    for call, text, day in rows:
        await store.save(call, text, day)


async def test_list_filters_by_day_and_caller(integration_session):
    store = DbTranscriptStore(integration_session)
    await _seed(
        store,
        [
            (
                CallRecord(
                    call_id="a1",
                    started_at="2026-10-01T09:00:00",
                    caller="0362698948",
                    talk_seconds=30,
                ),
                "S1: a",
                date(2026, 10, 1),
            ),
            (
                CallRecord(
                    call_id="a2",
                    started_at="2026-10-01T13:00:00",
                    caller="0902065233",
                    talk_seconds=60,
                ),
                "S1: b",
                date(2026, 10, 1),
            ),
            (
                CallRecord(
                    call_id="a3",
                    started_at="2026-10-02T10:00:00",
                    caller="0362698948",
                    talk_seconds=15,
                ),
                "S1: c",
                date(2026, 10, 2),
            ),
        ],
    )

    by_day, day_total = await list_call_transcripts(integration_session, day=date(2026, 10, 1))
    assert {row.call_id for row in by_day} == {"a1", "a2"}
    assert day_total == 2

    by_caller, caller_total = await list_call_transcripts(
        integration_session, caller="03626"
    )
    assert {row.call_id for row in by_caller} == {"a1", "a3"}
    assert caller_total == 2

    both, both_total = await list_call_transcripts(
        integration_session, day=date(2026, 10, 1), caller="03626"
    )
    assert [row.call_id for row in both] == ["a1"]
    assert both_total == 1


async def test_list_paginates_newest_call_first(integration_session):
    store = DbTranscriptStore(integration_session)
    await _seed(
        store,
        [
            (
                CallRecord(call_id="m1", started_at="2026-10-01T09:00:00", caller="1", talk_seconds=1),
                "s1",
                date(2026, 10, 1),
            ),
            (
                CallRecord(call_id="m2", started_at="2026-10-01T13:00:00", caller="2", talk_seconds=1),
                "s2",
                date(2026, 10, 1),
            ),
            (
                CallRecord(call_id="m3", started_at="2026-10-01T17:00:00", caller="3", talk_seconds=1),
                "s3",
                date(2026, 10, 1),
            ),
        ],
    )

    page1, total = await list_call_transcripts(integration_session, page=1, page_size=2)
    page2, _ = await list_call_transcripts(integration_session, page=2, page_size=2)

    assert total == 3
    assert [row.call_id for row in page1] == ["m3", "m2"]
    assert [row.call_id for row in page2] == ["m1"]


async def test_get_by_call_id(integration_session):
    store = DbTranscriptStore(integration_session)
    await store.save(_call("1791181502"), "Nội dung đầy đủ.", date(2026, 10, 3))

    found = await get_call_transcript(integration_session, "1791181502")
    assert found is not None
    assert found.transcript == "Nội dung đầy đủ."
    assert await get_call_transcript(integration_session, "khong-ton-tai") is None


async def test_a_day_without_a_marker_was_never_fetched(integration_session):
    assert await get_day_state(integration_session, date(2026, 10, 18)) is None


async def test_recording_a_day_marker_stores_its_counts(integration_session):
    row = await record_day_state(
        integration_session,
        date(2026, 10, 18),
        status=DAY_STATUS_CHECKED,
        call_count=3,
        recordable_count=1,
        transcript_count=1,
    )

    assert row.day == date(2026, 10, 18)
    assert row.status == DAY_STATUS_CHECKED
    assert row.call_count == 3
    assert row.recordable_count == 1
    assert row.transcript_count == 1
    assert row.error is None
    assert row.checked_at is not None

    stored = await get_day_state(integration_session, date(2026, 10, 18))
    assert stored is not None
    assert stored.transcript_count == 1


async def test_recording_a_day_marker_twice_updates_the_same_row(integration_session):
    """One row per day — a later fetch replaces the counts."""
    await record_day_state(
        integration_session,
        date(2026, 10, 19),
        status=DAY_STATUS_ERROR,
        error="CloudFone không phản hồi",
    )
    row = await record_day_state(
        integration_session,
        date(2026, 10, 19),
        status=DAY_STATUS_CHECKED,
        call_count=6,
        recordable_count=5,
        transcript_count=5,
    )

    assert row.status == DAY_STATUS_CHECKED
    assert row.error is None
    assert row.call_count == 6
    stored = await get_day_state(integration_session, date(2026, 10, 19))
    assert stored is not None
    assert stored.transcript_count == 5
