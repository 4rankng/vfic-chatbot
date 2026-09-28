"""Regression guards for REL-05 — the blank-only gender rule must be atomic.

The rule used to live in the adapter as a read-then-write: ``stored_gender``
read the row, ``record_inferred_gender`` re-read it, and the SQL update was an
unconditional ``SET gender = :gender``. A provider (OA profile enrichment) or a
recruiter committing between the read and the write therefore had its value
replaced, and because ``version``/``updated_at`` never moved the console could
not show the change.

The guard now lives in the statement. These tests pin:

* the generated UPDATE carries ``gender IS NULL OR btrim(gender) = ''`` when the
  caller is not overriding, so a concurrent non-blank value matches no row;
* ``override=True`` (the candidate explicitly self-referring) drops the guard
  and advances ``version``, and
* the adapter hands ``override`` through instead of pre-deciding on a stale read.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.recruitment.infrastructure.service_adapters import ServiceLeadGenderAdapter
from app.services.lead.repository import LeadRepository

LEAD_ID = 5


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))


class _RowcountResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeExecuteSession:
    """Captures the statements handed to ``execute`` and returns a fixed rowcount."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _RowcountResult(self.rowcount)


# --- the statement itself -----------------------------------------------------


@pytest.mark.asyncio
async def test_blank_only_guard_is_part_of_the_statement():
    db = _FakeExecuteSession(rowcount=1)

    assert await LeadRepository(db).set_gender_by_id(LEAD_ID, "female") is True

    sql = _sql(db.statements[0])
    assert sql.startswith("UPDATE leads")
    assert "leads.id = " in sql
    # A row that acquired a value between the caller's read and this write is
    # excluded by the statement itself — there is no window to lose.
    assert "leads.gender IS NULL" in sql
    assert "btrim(leads.gender) = " in sql


@pytest.mark.asyncio
async def test_a_concurrent_non_blank_gender_is_never_overwritten():
    """The guarded write matches no row, so the caller is told nothing changed."""
    db = _FakeExecuteSession(rowcount=0)

    assert await LeadRepository(db).set_gender_by_id(LEAD_ID, "female") is False


@pytest.mark.asyncio
async def test_override_drops_the_guard_and_advances_the_version():
    db = _FakeExecuteSession(rowcount=1)

    assert await LeadRepository(db).set_gender_by_id(LEAD_ID, "female", override=True) is True

    sql = _sql(db.statements[0])
    assert "IS NULL" not in sql.upper()
    assert "btrim" not in sql
    assert "leads.version + " in sql


@pytest.mark.asyncio
async def test_every_write_moves_updated_at_and_only_override_moves_version():
    plain = _FakeExecuteSession(rowcount=1)
    override = _FakeExecuteSession(rowcount=1)

    await LeadRepository(plain).set_gender_by_id(LEAD_ID, "female")
    await LeadRepository(override).set_gender_by_id(LEAD_ID, "female", override=True)

    plain_sql = _sql(plain.statements[0])
    override_sql = _sql(override.statements[0])
    assert "updated_at=now()" in plain_sql
    assert "updated_at=now()" in override_sql
    assert "version" not in plain_sql
    assert "leads.version + " in override_sql


# --- the adapter hands the decision to the statement --------------------------


class _FakeLeadRepository:
    """Records how the adapter asked for the write."""

    calls: list = []

    def __init__(self, _db) -> None:
        pass

    async def set_gender_by_id(self, lead_id: int, gender: str, *, override: bool = False) -> bool:
        _FakeLeadRepository.calls.append((lead_id, gender, override))
        return True


@pytest.fixture()
def adapter(monkeypatch):
    _FakeLeadRepository.calls = []
    monkeypatch.setattr("app.services.lead.repository.LeadRepository", _FakeLeadRepository)
    return ServiceLeadGenderAdapter(AsyncMock())


@pytest.mark.asyncio
async def test_adapter_does_not_pre_decide_on_a_stale_read(adapter):
    """A prefetched non-blank row no longer short-circuits the write.

    The adapter used to return early on the value it read earlier; that read is
    exactly what raced. It now always asks the guarded statement.
    """
    stale = {"id": LEAD_ID, "gender": "male"}

    assert await adapter.record_inferred_gender("chat-1", "female", lead=stale) is True
    assert _FakeLeadRepository.calls == [(LEAD_ID, "female", False)]


@pytest.mark.asyncio
async def test_adapter_passes_override_through(adapter):
    assert (
        await adapter.record_inferred_gender("chat-1", "female", override=True, lead={"id": LEAD_ID})
        is True
    )
    assert _FakeLeadRepository.calls == [(LEAD_ID, "female", True)]


@pytest.mark.asyncio
async def test_adapter_still_ignores_unsupported_gender_values(adapter):
    assert await adapter.record_inferred_gender("chat-1", "unknown", lead={"id": LEAD_ID}) is False
    assert _FakeLeadRepository.calls == []


@pytest.mark.asyncio
async def test_adapter_writes_nothing_without_a_resolved_lead(adapter):
    assert await adapter.record_inferred_gender("chat-1", "male", lead={"gender": None}) is False
    assert _FakeLeadRepository.calls == []


# --- profile-name capture: blank-only, written through the row's own key ------


class _FakeNameLeadRepository:
    """Stands in for LeadRepository during profile-name persistence tests.

    ``writes`` records which key each upsert went through, so a test can assert
    that a contact-keyed lead is never addressed by the chat id.
    """

    instances: list = []
    results: list = []

    def __init__(self, _db) -> None:
        self.upserts: list[dict] = []
        self.writes: list[str] = []
        _FakeNameLeadRepository.instances.append(self)

    async def by_zalo_id(self, _chat_id):
        return None

    async def by_contact_id(self, _contact_id):
        return None

    async def upsert(self, lead: dict):
        self.upserts.append(lead)
        self.writes.append(f"zalo:{lead.get('zalo_id')}")
        return _FakeNameLeadRepository.results.pop(0)

    async def upsert_by_contact(self, contact_id, lead: dict):
        self.upserts.append(lead)
        self.writes.append(f"contact:{contact_id}")
        return _FakeNameLeadRepository.results.pop(0)


@pytest.fixture()
def name_db(monkeypatch):
    """An async db stub whose commit is recorded and whose scalar finds no lead."""
    from unittest.mock import AsyncMock

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
    db.commit = AsyncMock()
    db.add = AsyncMock()
    monkeypatch.setattr(
        "app.services.lead.repository.LeadRepository", _FakeNameLeadRepository
    )
    _FakeNameLeadRepository.instances = []
    _FakeNameLeadRepository.results = [42]
    return db


@pytest.mark.asyncio
async def test_record_profile_name_persists_blank_zalo_keyed_lead(name_db):
    from app.recruitment.infrastructure.service_adapters import ServiceLeadGenderAdapter

    adapter = ServiceLeadGenderAdapter(name_db)
    lead = {"id": 7, "zalo_id": "oa:544936713681674566", "name": ""}

    assert await adapter.record_profile_name("oa:544936713681674566", "Duc Huy Nguyen", lead=lead) is True
    upserts = _FakeNameLeadRepository.instances[0].upserts
    assert len(upserts) == 1
    assert upserts[0]["zalo_id"] == "oa:544936713681674566"
    assert upserts[0]["name"] == "Duc Huy Nguyen"
    assert upserts[0]["phone"] is None
    name_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_profile_name_merges_contact_keyed_lead_by_contact(name_db):
    """A Messenger lead (NULL zalo_id) is written by contact, never by chat id.

    The page-scoped PSID is a provider recipient, not a
    ``conversations.zalo_chat_id``, so offering it to ``leads.zalo_id`` violates
    ``leads_zalo_id_fkey`` and rolls the whole write back.
    """
    from app.recruitment.infrastructure.service_adapters import ServiceLeadGenderAdapter

    adapter = ServiceLeadGenderAdapter(name_db)
    lead = {"id": 7, "zalo_id": None, "contact_id": "contact-1", "name": ""}

    assert await adapter.record_profile_name(
        "28225543490450146", "Duc Huy Nguyen", lead=lead
    ) is True
    repo = _FakeNameLeadRepository.instances[0]
    assert repo.writes == ["contact:contact-1"]
    assert repo.upserts[0]["name"] == "Duc Huy Nguyen"
    name_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_profile_name_refuses_unaddressable_lead_row(name_db):
    """A lead row carrying neither key cannot be written at all."""
    from app.recruitment.infrastructure.service_adapters import ServiceLeadGenderAdapter

    adapter = ServiceLeadGenderAdapter(name_db)
    lead = {"id": 7, "zalo_id": None, "contact_id": None, "name": ""}

    assert await adapter.record_profile_name("z1", "Duc Huy Nguyen", lead=lead) is False
    assert _FakeNameLeadRepository.instances == []
    name_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_profile_name_refuses_leadless_non_oa_chat(name_db):
    from app.recruitment.infrastructure.service_adapters import ServiceLeadGenderAdapter

    adapter = ServiceLeadGenderAdapter(name_db)

    assert await adapter.record_profile_name("raw-bot-id", "Duc Huy Nguyen", lead=None) is False
    assert all(not repo.upserts for repo in _FakeNameLeadRepository.instances)


@pytest.mark.asyncio
async def test_record_profile_name_blank_name_is_a_no_op(name_db):
    from app.recruitment.infrastructure.service_adapters import ServiceLeadGenderAdapter

    adapter = ServiceLeadGenderAdapter(name_db)

    assert await adapter.record_profile_name("oa:1", "   ", lead=None) is False
    assert _FakeNameLeadRepository.instances == []
