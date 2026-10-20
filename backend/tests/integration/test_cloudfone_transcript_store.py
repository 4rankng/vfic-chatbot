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
from app.services.cloudfone_transcripts import DbTranscriptStore

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
