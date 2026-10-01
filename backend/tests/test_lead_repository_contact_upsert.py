"""The contact-keyed lead write must never offer a chat id to ``leads.zalo_id``.

``leads.zalo_id`` carries a foreign key to ``conversations(zalo_chat_id)`` and a
Messenger conversation has no Zalo chat id — its recipient id is the page-scoped
PSID. Writing that PSID into ``leads.zalo_id`` raised
``ForeignKeyViolationError``, which the persistence worker swallowed into a
warning, so no Messenger candidate ever had a name or phone in the CRM. These
tests pin the two statements the contact path is allowed to issue.
"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
CONTACT_ID = "84bf2955-ac65-4025-94c8-b40d7c6ed3b2"


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

    def __init__(self, scalars: list, read_scalars: list | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.flushed = 0
        self._scalars = list(scalars)
        self._read_scalars = list(read_scalars or [])

    async def execute(self, statement, params=None):
        text = str(statement)
        self.calls.append((text, dict(params or {})))
        if "pg_advisory_xact_lock" in text:
            return _Result(None)
        return _Result(self._scalars.pop(0) if self._scalars else None)

    async def flush(self) -> None:
        self.flushed += 1

    async def scalar(self, statement):
        self.calls.append((str(statement), dict(statement.compile().params)))
        return self._read_scalars.pop(0) if self._read_scalars else None


def _sql_of(call: tuple[str, dict]) -> str:
    return " ".join(call[0].split())


@pytest.mark.asyncio
async def test_upsert_by_contact_merges_the_existing_row_without_an_insert():
    """The trigger already created the lead, so the write is a merge."""
    db = _RecordingSession(scalars=[130], read_scalars=[130, None])
    repo = LeadRepository(cast(AsyncSession, db))

    lead_id = await repo.upsert_by_contact(CONTACT_ID, LEAD)

    assert lead_id == 130
    assert db.flushed == 1
    statements = [_sql_of(call) for call in db.calls]
    assert len(statements) == 4, statements
    assert "pg_advisory_xact_lock" in statements[0]
    assert "leads.contact_id =" in statements[1]
    assert "FOR UPDATE" in statements[1]
    assert "lead_events.lead_id =" in statements[2]
    assert "LIMIT" in statements[2]
    assert statements[3] == " ".join(_UPDATE_BY_CONTACT_SQL.text.split())
    assert "INSERT INTO leads" not in statements[3]
    assert db.calls[3][1]["contact_id"] == CONTACT_ID


@pytest.mark.asyncio
async def test_upsert_by_contact_inserts_with_a_null_zalo_id_when_no_row_exists():
    db = _RecordingSession(scalars=[None, 131])
    repo = LeadRepository(cast(AsyncSession, db))

    lead_id = await repo.upsert_by_contact(CONTACT_ID, LEAD)

    assert lead_id == 131
    insert = _sql_of(db.calls[-1])
    assert insert == " ".join(_INSERT_BY_CONTACT_SQL.text.split())
    # zalo_id is a literal NULL in the VALUES list, never a bound chat id.
    assert "NULL" in insert
    assert "VALUES (CAST(:contact_id AS uuid), NULL" in insert
    assert db.calls[-1][1]["contact_id"] == CONTACT_ID
    # The page-scoped PSID travels as an unused patch key, not as the row key.
    assert db.calls[-1][1]["zalo_id"] == "28225543490450146"


@pytest.mark.asyncio
async def test_upsert_by_contact_takes_the_contact_lock_before_the_write():
    db = _RecordingSession(scalars=[130])

    await LeadRepository(cast(AsyncSession, db)).upsert_by_contact(CONTACT_ID, LEAD)

    assert "pg_advisory_xact_lock" in _sql_of(db.calls[0])
    assert "FOR UPDATE" in _sql_of(db.calls[1])
    assert "UPDATE leads" in _sql_of(db.calls[-1])


@pytest.mark.asyncio
async def test_the_zalo_keyed_upsert_is_unchanged_by_the_contact_path():
    """Zalo rows still merge on ``ON CONFLICT (zalo_id)`` — the proven path."""
    db = _RecordingSession(scalars=[42])
    repo = LeadRepository(cast(AsyncSession, db))

    assert await repo.upsert(LEAD) == 42
    sql = " ".join(_UPSQL.text.split())
    assert sql == " ".join(_sql_of(db.calls[-1]).split())
    assert "leads.zalo_id =" in _sql_of(db.calls[0])
    assert "FOR UPDATE" in _sql_of(db.calls[0])
    assert "ON CONFLICT (zalo_id) DO UPDATE SET" in sql
    assert db.flushed == 1
    assert len(db.calls) == 2
    assert sum("INSERT INTO leads" in _sql_of(call) for call in db.calls) == 1
    assert all("pg_advisory_xact_lock" not in _sql_of(call) for call in db.calls)
