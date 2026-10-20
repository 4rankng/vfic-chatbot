"""Real-DB tests for the Cloudfone transcript store.

The unit suite drives the ``TranscriptStore`` seam with fakes, so the SQLAlchemy
row mapping of migration 0076 shipped unexercised: a column mismatch between
model and migration would only surface in production, on the first daily tick.
These tests commit real rows against the disposable database so that drift is
caught here instead.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.cloudfone import CallRecord
from app.services.cloudfone_transcripts import (
    DbTranscriptStore,
    get_call_transcript,
    list_call_transcripts,
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
