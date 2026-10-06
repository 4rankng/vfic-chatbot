"""Regression guards for SEC-02 — the lead by-id routes must honour viewer scope.

Every lead by-id route used to load the row by primary key with no ownership
predicate, so any authenticated recruiter could read and mutate every other
recruiter's candidate PII. The list/board queries and the conversation detail
path already enforced the invariant; the by-id path did not.

Two layers are pinned here:

* the repository read really carries the scope predicate (admin = unrestricted,
  recruiter = own-or-unassigned) and returns ``None`` when the id is out of
  scope, and
* every by-id route maps that ``None`` to **404** — never 200 and never 403, so
  the sequential id space stays unprobeable — while an admin still gets 200.

The route layer runs against a ``LeadService`` double that applies the same
invariant, because the real predicate is compiled SQL and this suite has no
database (see ``tests/conftest.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.dialects import postgresql

import app.api.installation_dependencies as installation_dependencies
import app.services.presence as presence
from app.api.auth_dependencies import get_current_user
from app.api.leads import router as leads_router
from app.core.errors import register_domain_exception_handlers
from app.models.lead import FollowUpTask, Lead, LeadEvent
from app.models.user import Role
from app.recruitment.domain.statuses import FollowupStatus, LeadStage
from app.services.lead import LeadService
from app.services.lead.repository import LeadRepository
from app.shared.domain.errors import BadRequestError
from app.shared.infrastructure.db import get_request_db

VIEWER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
LEAD_ID = 7

_app = FastAPI()
register_domain_exception_handlers(_app)
_app.include_router(leads_router, prefix="/api/v1")


def _viewer(role: Role, uid: uuid.UUID = VIEWER_ID) -> SimpleNamespace:
    return SimpleNamespace(id=uid, role=role, email="viewer@test", full_name="Viewer")


def _lead(assigned_to: uuid.UUID | None = None) -> Lead:
    # No zalo_id: the memories route then short-circuits instead of reaching
    # MemoryRepository, which is out of scope for these tests.
    lead = Lead(zalo_id=None, name="Anh", lead_stage=LeadStage.NEW)
    lead.id = LEAD_ID
    lead.version = 1
    lead.assigned_recruiter_id = assigned_to
    lead.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lead.updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    return lead


def _followup() -> FollowUpTask:
    task = FollowUpTask(
        lead_id=LEAD_ID,
        due_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        note=None,
        status=FollowupStatus.PENDING,
    )
    task.id = 11
    task.created_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    return task


def _event() -> LeadEvent:
    event = LeadEvent(lead_id=LEAD_ID, event_type="assign", payload={"recruiter_id": None})
    event.id = 12
    event.created_at = datetime(2026, 1, 4, tzinfo=timezone.utc)
    return event


_ASSIST = {
    "summary": "Anh",
    "missing": [],
    "reply": "Dạ em chào anh",
    "next_action": "Gọi lại",
    "mode_label": "Bot",
    "signals": [],
}
_TAG = {"key": "has_phone", "label": "Có SĐT", "tone": "good", "system": True}


class _FakeLeadService:
    """``LeadService`` double applying the own-or-unassigned invariant.

    ``seen`` records every viewer the routes threaded down, so a route that
    forgets to pass the current user fails the assertion instead of silently
    reading the row.
    """

    def __init__(self, lead: Lead, seen: list) -> None:
        self._lead = lead
        self._seen = seen

    def __call__(self, _db):  # stands in for ``LeadService(db)``
        return self

    async def get_visible(self, lead_id: int, *, viewer):
        self._seen.append(viewer)
        if lead_id != self._lead.id:
            return None
        if viewer.role == Role.admin:
            return self._lead
        if self._lead.assigned_recruiter_id in (None, viewer.id):
            return self._lead
        return None

    async def update(self, lead, changes):
        return lead

    async def assign(self, lead, recruiter_id, *, actor):
        return lead

    async def set_stage(self, lead, stage, *, actor):
        return lead

    async def create_followup(self, lead, due_at, note, *, actor):
        return _followup()

    async def list_operational_tags(self, lead):
        return [dict(_TAG)]

    async def replace_manual_tags(self, lead, keys, *, actor, tags=None):
        return [dict(_TAG)]

    async def build_chatops_assist(self, lead):
        return dict(_ASSIST)

    async def apply_chatops_action(self, lead, action, *, actor):
        return lead

    async def list_followups(self, lead_id):
        return [_followup()]

    async def list_events(self, lead_id):
        return [_event()]


class _StubPolicy:
    async def require_capability_or_legacy(self, _capability_id):
        return None


@pytest.fixture()
def seen_viewers() -> list:
    return []


@pytest.fixture()
def lead() -> Lead:
    return _lead(assigned_to=OTHER_ID)


@pytest.fixture(autouse=True)
def _no_capability_gate(monkeypatch):
    """The router-level capability guard is not what these tests exercise."""
    monkeypatch.setattr(
        installation_dependencies,
        "build_installation_access_policy",
        lambda _db: _StubPolicy(),
    )


@pytest.fixture(autouse=True)
def _no_presence_backend(monkeypatch):
    async def _empty(*_args, **_kwargs):
        return []

    monkeypatch.setattr(presence, "get_viewers", _empty)
    monkeypatch.setattr(presence, "get_typing_users", _empty)


@pytest.fixture()
def client(lead, seen_viewers, monkeypatch):
    """An ASGI client over the real leads router with a fake service + session."""

    def _build(user):
        monkeypatch.setattr(
            "app.api.leads.LeadService", _FakeLeadService(lead, seen_viewers)
        )

        async def override_user():
            return user

        async def override_db():
            yield AsyncMock()

        _app.dependency_overrides[get_current_user] = override_user
        _app.dependency_overrides[get_request_db] = override_db
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app), base_url="http://testserver"
        )

    yield _build
    _app.dependency_overrides.clear()


# --- every by-id route --------------------------------------------------------

READ_ROUTES = [
    ("get", f"/api/v1/leads/{LEAD_ID}", None, 200),
    ("get", f"/api/v1/leads/{LEAD_ID}/tags", None, 200),
    ("get", f"/api/v1/leads/{LEAD_ID}/assist", None, 200),
    ("get", f"/api/v1/leads/{LEAD_ID}/follow-ups", None, 200),
    ("get", f"/api/v1/leads/{LEAD_ID}/events", None, 200),
    ("get", f"/api/v1/leads/{LEAD_ID}/project-interests", None, 200),
    ("get", f"/api/v1/leads/{LEAD_ID}/memories", None, 200),
    ("get", f"/api/v1/leads/{LEAD_ID}/presence", None, 200),
]

MUTATE_ROUTES = [
    ("patch", f"/api/v1/leads/{LEAD_ID}", {"name": "Sửa"}, 200),
    ("post", f"/api/v1/leads/{LEAD_ID}/assign", {"recruiter_id": str(VIEWER_ID)}, 200),
    ("post", f"/api/v1/leads/{LEAD_ID}/stage", {"stage": "CONTACTING"}, 200),
    ("post", f"/api/v1/leads/{LEAD_ID}/follow-ups", {"due_at": "2026-02-01T09:00:00Z"}, 201),
    ("put", f"/api/v1/leads/{LEAD_ID}/tags", {"keys": [], "tags": []}, 200),
    ("post", f"/api/v1/leads/{LEAD_ID}/chatops-actions/mark_hot", None, 200),
]

ROUTES = READ_ROUTES + MUTATE_ROUTES


async def _call(http, method: str, url: str, body):
    return await getattr(http, method)(url, **({"json": body} if body is not None else {}))


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "url", "body", "_status"), ROUTES)
async def test_recruiter_gets_404_on_another_recruiters_lead(client, method, url, body, _status):
    """Out-of-scope ids must be indistinguishable from missing ones."""
    async with client(_viewer(Role.recruiter)) as http:
        response = await _call(http, method, url, body)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "lead not found"


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "url", "body", "status"), ROUTES)
async def test_admin_still_reaches_every_by_id_route(client, method, url, body, status):
    async with client(_viewer(Role.admin)) as http:
        response = await _call(http, method, url, body)

    assert response.status_code == status, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "url", "body", "status"), ROUTES)
async def test_recruiter_reaches_their_own_lead(client, lead, method, url, body, status):
    lead.assigned_recruiter_id = VIEWER_ID

    async with client(_viewer(Role.recruiter)) as http:
        response = await _call(http, method, url, body)

    assert response.status_code == status, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "url", "body", "status"), ROUTES)
async def test_recruiter_reaches_an_unassigned_lead(client, lead, method, url, body, status):
    lead.assigned_recruiter_id = None

    async with client(_viewer(Role.recruiter)) as http:
        response = await _call(http, method, url, body)

    assert response.status_code == status, response.text


@pytest.mark.asyncio
async def test_routes_thread_the_current_user_into_the_scoped_read(client, seen_viewers):
    recruiter = _viewer(Role.recruiter)

    async with client(recruiter) as http:
        await http.get(f"/api/v1/leads/{LEAD_ID}")
        await http.patch(f"/api/v1/leads/{LEAD_ID}", json={"name": "Sửa"})

    assert seen_viewers == [recruiter, recruiter]


# --- the scoped read itself ---------------------------------------------------


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))


class _ScalarResult:
    def __init__(self, row) -> None:
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    """Captures the statements a repository hands to ``scalars``."""

    def __init__(self, row=None) -> None:
        self.row = row
        self.statements: list = []

    async def scalars(self, stmt):
        self.statements.append(stmt)
        return _ScalarResult(self.row)


@pytest.mark.asyncio
async def test_get_visible_scopes_a_recruiter_to_own_or_unassigned():
    db = _FakeSession(row=None)

    assert await LeadRepository(db).get_visible(LEAD_ID, viewer=_viewer(Role.recruiter)) is None

    sql = _sql(db.statements[0])
    assert "leads.id = " in sql
    assert "leads.assigned_recruiter_id = " in sql
    assert "IS NULL" in sql.upper()


@pytest.mark.asyncio
async def test_get_visible_leaves_an_admin_unrestricted():
    lead = _lead(assigned_to=OTHER_ID)
    db = _FakeSession(row=lead)

    assert await LeadRepository(db).get_visible(LEAD_ID, viewer=_viewer(Role.admin)) is lead

    sql = _sql(db.statements[0])
    assert "leads.id = " in sql
    assert "IS NULL" not in sql.upper()


@pytest.mark.asyncio
async def test_get_visible_returns_the_row_when_the_scope_matches():
    lead = _lead(assigned_to=VIEWER_ID)
    db = _FakeSession(row=lead)

    assert await LeadRepository(db).get_visible(LEAD_ID, viewer=_viewer(Role.recruiter)) is lead


@pytest.mark.asyncio
async def test_service_get_visible_delegates_the_viewer_to_the_repository(monkeypatch):
    lead = _lead(assigned_to=VIEWER_ID)
    service = LeadService(AsyncMock())
    recorder = _FakeSession(row=lead)
    monkeypatch.setattr(service, "repo", LeadRepository(recorder))
    viewer = _viewer(Role.recruiter)

    assert await service.get_visible(LEAD_ID, viewer=viewer) is lead

    sql = _sql(recorder.statements[0])
    assert "leads.assigned_recruiter_id = " in sql


# --- assignee validation ------------------------------------------------------


class _RowcountResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


@pytest.mark.asyncio
async def test_assign_rejects_a_recruiter_id_that_is_not_an_enabled_user():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    service = LeadService(db)

    with pytest.raises(BadRequestError):
        await service.assign(_lead(), OTHER_ID, actor=_viewer(Role.admin))

    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_assign_proceeds_for_an_enabled_user():
    lead = _lead()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=OTHER_ID)
    db.execute = AsyncMock(return_value=_RowcountResult(rowcount=1))
    db.add = MagicMock()
    service = LeadService(db)
    service.events = AsyncMock()

    assert await service.assign(lead, OTHER_ID, actor=_viewer(Role.admin)) is lead
    db.execute.assert_awaited()
