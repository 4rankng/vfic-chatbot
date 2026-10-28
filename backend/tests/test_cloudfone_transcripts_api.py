"""GET /admin/integrations/cloudfone/transcripts[/{call_id}]: viewer contract.

The daily insights pass stores transcripts in ``cloudfone_call_transcripts``;
this pair of read endpoints serves the call-records viewer — every signed-in
workspace user, not just admins (CHAT-15). These tests drive the routes over
HTTP on a bare app as a non-admin principal and pin the projection contract:
the list carries a 160-char preview (never the full text), the detail carries
the full transcript, and an unknown call id answers 404 with the domain
error's Vietnamese reason. Filter/paging SQL behavior is covered against a
real database in ``tests/integration/test_cloudfone_transcript_store.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import integrations as integrations_api
from app.api.auth_dependencies import get_current_user
from app.core.errors import register_domain_exception_handlers
from app.models.cloudfone import CloudfoneCallTranscript, CloudfoneTranscriptDay
from app.shared.infrastructure.db import get_request_db

_LONG_TRANSCRIPT = "S1: Alo ạ? " + "khách hỏi về giá dịch vụ. " * 12


def _row(call_id: str = "1790848955", transcript: str = "S1: Alo ạ?") -> CloudfoneCallTranscript:
    return CloudfoneCallTranscript(
        call_id=call_id,
        day=date(2026, 10, 1),
        started_at="2026-10-01T17:02:35",
        caller="0362698948",
        talk_seconds=98,
        transcript=transcript,
        created_at=datetime(2026, 10, 2, 1, 0),
    )


class _ListSession:
    """Typed double: answers the count query, the page query and the day marker."""

    def __init__(self, rows, total: int, day_state=None) -> None:
        self._rows = rows
        self._total = total
        self._day_state = day_state

    async def scalar(self, query):
        # The day marker is a different table than the transcript page/count.
        if "cloudfone_transcript_days" in str(query):
            return self._day_state
        return self._total

    async def scalars(self, _query):
        return SimpleNamespace(all=lambda: list(self._rows))


class _DetailSession:
    """Typed double: answers the by-call_id lookup."""

    def __init__(self, row) -> None:
        self._row = row

    async def scalar(self, _query):
        return self._row


def _client(session) -> TestClient:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(integrations_api.router, prefix="/api/v1")
    # CHAT-15: the records endpoints serve non-admins, so the default principal
    # is a recruiter — every projection test doubles as the permission pin.
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="recruiter"
    )
    app.dependency_overrides[get_request_db] = lambda: session
    return TestClient(app)


def test_list_returns_the_page_projection_with_a_bounded_preview() -> None:
    client = _client(_ListSession([_row(transcript=_LONG_TRANSCRIPT)], total=1))

    response = client.get("/api/v1/admin/integrations/cloudfone/transcripts")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    [item] = body["items"]
    assert item["call_id"] == "1790848955"
    assert item["day"] == "2026-10-01"
    assert item["started_at"] == "2026-10-01T17:02:35"
    assert item["caller"] == "0362698948"
    assert item["talk_seconds"] == 98
    assert len(item["transcript_preview"]) == 160
    assert item["transcript_preview"] == _LONG_TRANSCRIPT[:160]
    # The list never ships the full text — that is the detail endpoint's job.
    assert "transcript" not in item


def test_list_query_bounds_are_enforced() -> None:
    client = _client(_ListSession([], total=0))

    assert client.get("/api/v1/admin/integrations/cloudfone/transcripts?page=0").status_code == 422
    assert (
        client.get("/api/v1/admin/integrations/cloudfone/transcripts?page_size=101").status_code
        == 422
    )
    ok = client.get(
        "/api/v1/admin/integrations/cloudfone/transcripts",
        params={"day": "2026-10-01", "caller": "036", "page": 2, "page_size": 5},
    )
    assert ok.status_code == 200
    assert ok.json()["page"] == 2
    assert ok.json()["page_size"] == 5


def test_list_reports_the_day_marker_so_the_viewer_knows_what_to_fetch() -> None:
    """The day filter rides along with the marker of that day's inspection.

    ``unchecked`` means the day was never fetched from Cloudfone (the viewer
    fetches it on demand); ``checked`` means the day is known — and the
    viewer leaves it alone.
    """
    unchecked = _client(_ListSession([], total=0)).get(
        "/api/v1/admin/integrations/cloudfone/transcripts",
        params={"day": "2026-10-01"},
    )
    assert unchecked.status_code == 200
    assert unchecked.json()["day_state"] == {
        "day": "2026-10-01",
        "status": "unchecked",
        "call_count": 0,
        "recordable_count": 0,
        "transcript_count": 0,
        "checked_at": None,
        "error": None,
    }

    checked = _client(
        _ListSession(
            [],
            total=0,
            day_state=CloudfoneTranscriptDay(
                day=date(2026, 10, 1),
                status="checked",
                call_count=3,
                recordable_count=1,
                transcript_count=1,
                checked_at=datetime(2026, 10, 2, 1, 0),
            ),
        )
    ).get(
        "/api/v1/admin/integrations/cloudfone/transcripts",
        params={"day": "2026-10-01"},
    )
    assert checked.status_code == 200
    state = checked.json()["day_state"]
    assert state["status"] == "checked"
    assert state["call_count"] == 3
    assert state["transcript_count"] == 1


def test_list_without_a_day_filter_carries_no_marker() -> None:
    client = _client(_ListSession([_row()], total=1))

    body = client.get("/api/v1/admin/integrations/cloudfone/transcripts").json()

    assert body["day_state"] is None


def test_detail_returns_the_full_transcript() -> None:
    client = _client(_DetailSession(_row(transcript=_LONG_TRANSCRIPT)))

    response = client.get("/api/v1/admin/integrations/cloudfone/transcripts/1790848955")

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == _LONG_TRANSCRIPT
    assert body["transcript_preview"] == _LONG_TRANSCRIPT[:160]


def test_detail_unknown_call_is_404() -> None:
    client = _client(_DetailSession(None))

    response = client.get("/api/v1/admin/integrations/cloudfone/transcripts/khong-ton-tai")

    assert response.status_code == 404
    assert "Không tìm thấy bản ghi cuộc gọi." in response.text


def test_backfill_returns_the_day_fetch_outcome(monkeypatch) -> None:
    """The on-demand fetch answers with what it did, so the viewer can refresh."""
    from app.services import cloudfone as cloudfone_service

    session = _ListSession([], total=0)

    async def fake_backfill(db, day, *, force=False):
        assert db is session
        assert day == date(2026, 10, 18)
        assert force is False
        return cloudfone_service.CloudfoneTranscriptBackfill(
            day=day,
            status=cloudfone_service.BACKFILL_CHECKED,
            calls=3,
            recordable=1,
            transcripts=1,
            added=1,
            remaining=0,
        )

    monkeypatch.setattr(cloudfone_service, "backfill_day_transcripts", fake_backfill)
    client = _client(session)

    response = client.post(
        "/api/v1/admin/integrations/cloudfone/transcripts/backfill",
        json={"day": "2026-10-18"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["day"] == "2026-10-18"
    assert body["status"] == "checked"
    assert body["calls"] == 3
    assert body["added"] == 1
    assert body["remaining"] == 0


def test_backfill_rejects_a_day_that_is_not_a_date() -> None:
    client = _client(_ListSession([], total=0))

    response = client.post(
        "/api/v1/admin/integrations/cloudfone/transcripts/backfill",
        json={"day": "khong-phai-ngay"},
    )

    assert response.status_code == 422
