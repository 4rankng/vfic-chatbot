"""The contact-keyed lead write must never offer a chat id to ``leads.zalo_id``.

``leads.zalo_id`` carries a foreign key to ``conversations(zalo_chat_id)`` and a
Messenger conversation has no Zalo chat id — its recipient id is the page-scoped
PSID. Writing that PSID into ``leads.zalo_id`` raised
``ForeignKeyViolationError``, which the persistence worker swallowed into a
warning, so no Messenger candidate ever had a name or phone in the CRM. These
tests pin the two statements the contact path is allowed to issue.
"""

from __future__ import annotations

import pytest

from app.services.lead.repository import (
    _INSERT_BY_CONTACT_SQL,
    _UPDATE_BY_CONTACT_SQL,
    _UPSQL,
    LeadRepository,
)

LEAD = {
    "zalo_id": "28225543490450146",
    "name": "Hoàng sóng",
    "phone": "0566866899",
    "birth_year": None,
    "age": None,
    "living_area": None,
    "address": None,
    "gender": None,
    "region": "Vĩnh Bảo",
    "desired_job": "tài xế xe khách",
    "years_experience": None,
    "expected_salary": None,
    "lead_score": "warm",
    "notes": "ở Nam Am, Vĩnh Bảo",
}


class _Result:
    def __init__(self, scalar=None) -> None:
        self._scalar = scalar

    def scalar(self):
        return self._scalar


class _RecordingSession:
    """A session that records every statement and replays queued write results.

    ``scalars`` is consumed only by the write statements: the advisory lock
    returns no row and must not eat a queued result.
    """

    def __init__(self, scalars: list) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.flushed = 0
        self._scalars = list(scalars)

    async def execute(self, statement, params=None):
        text = str(statement)
        self.calls.append((text, dict(params or {})))
        if "pg_advisory_xact_lock" in text:
            return _Result(None)
        return _Result(self._scalars.pop(0) if self._scalars else None)

    async def flush(self) -> None:
        self.flushed += 1


def _sql_of(call: tuple[str, dict]) -> str:
    return " ".join(call[0].split())


@pytest.mark.asyncio
async def test_upsert_by_contact_merges_the_existing_row_without_an_insert():
    """The trigger already created the lead, so the write is a merge."""
    db = _RecordingSession(scalars=[130])
    repo = LeadRepository(db)

    lead_id = await repo.upsert_by_contact("contact-1", LEAD)

    assert lead_id == 130
    assert db.flushed == 1
    statements = [_sql_of(call) for call in db.calls]
    assert len(statements) == 2, statements
    assert "pg_advisory_xact_lock" in statements[0]
    assert statements[1] == " ".join(_UPDATE_BY_CONTACT_SQL.text.split())
    assert "INSERT INTO leads" not in statements[1]
    assert db.calls[1][1]["contact_id"] == "contact-1"


@pytest.mark.asyncio
async def test_upsert_by_contact_inserts_with_a_null_zalo_id_when_no_row_exists():
    db = _RecordingSession(scalars=[None, 131])
    repo = LeadRepository(db)

    lead_id = await repo.upsert_by_contact("contact-1", LEAD)

    assert lead_id == 131
    insert = _sql_of(db.calls[-1])
    assert insert == " ".join(_INSERT_BY_CONTACT_SQL.text.split())
    # zalo_id is a literal NULL in the VALUES list, never a bound chat id.
    assert "NULL" in insert
    assert "VALUES (CAST(:contact_id AS uuid), NULL" in insert
    assert db.calls[-1][1]["contact_id"] == "contact-1"
    # The page-scoped PSID travels as an unused patch key, not as the row key.
    assert db.calls[-1][1]["zalo_id"] == "28225543490450146"


@pytest.mark.asyncio
async def test_upsert_by_contact_takes_the_contact_lock_before_the_write():
    db = _RecordingSession(scalars=[130])

    await LeadRepository(db).upsert_by_contact("contact-1", LEAD)

    assert "pg_advisory_xact_lock" in _sql_of(db.calls[0])
    assert "UPDATE leads" in _sql_of(db.calls[1])


@pytest.mark.asyncio
async def test_the_zalo_keyed_upsert_is_unchanged_by_the_contact_path():
    """Zalo rows still merge on ``ON CONFLICT (zalo_id)`` — the proven path."""
    db = _RecordingSession(scalars=[42])
    repo = LeadRepository(db)

    assert await repo.upsert(LEAD) == 42
    sql = " ".join(_UPSQL.text.split())
    assert sql == " ".join(_sql_of(db.calls[0]).split())
    assert "ON CONFLICT (zalo_id) DO UPDATE SET" in sql
    assert db.flushed == 1
    assert len(db.calls) == 1, "the zalo path takes no advisory lock and inserts once"
