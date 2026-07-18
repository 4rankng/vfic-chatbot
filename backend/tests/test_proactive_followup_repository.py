"""Focused tests for provider-scoped proactive follow-up rule resolution."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.proactive import repository as proactive_repository


class _SqlResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _OrmScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _OrmResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _OrmScalars(self._rows)


class _Db:
    def __init__(self, sql_rows, conversations):
        self._sql_rows = sql_rows
        self._conversations = conversations

    async def execute(self, statement, params=None):  # noqa: ARG002
        if params is not None:
            return _SqlResult(self._sql_rows)
        return _OrmResult(self._conversations)


@pytest.mark.asyncio
async def test_find_eligible_conversations_caches_rules_per_provider(monkeypatch):
    now = datetime.now(timezone.utc)
    bot_conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_channel="bot",
        channel_identity=None,
        mode="BOT",
        last_inbound_at=now - timedelta(hours=2),
        followup_count=0,
    )
    oa_conv_a = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_channel="oa",
        channel_identity=None,
        mode="BOT",
        last_inbound_at=now - timedelta(hours=2),
        followup_count=0,
    )
    oa_conv_b = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_channel="oa",
        channel_identity=None,
        mode="BOT",
        last_inbound_at=now - timedelta(hours=2),
        followup_count=0,
    )
    db = _Db(
        [
            SimpleNamespace(_mapping={"id": bot_conv.id, "lead_score": "hot", "lead_stage": "NEW"}),
            SimpleNamespace(_mapping={"id": oa_conv_a.id, "lead_score": "hot", "lead_stage": "NEW"}),
            SimpleNamespace(_mapping={"id": oa_conv_b.id, "lead_score": "hot", "lead_stage": "NEW"}),
        ],
        [bot_conv, oa_conv_a, oa_conv_b],
    )
    calls: list[str] = []

    async def _rules(_db, *, provider="zalo_bot"):
        calls.append(provider)
        return proactive_repository.normalize_followup_rules(None)

    monkeypatch.setattr(proactive_repository, "active_followup_rules", _rules)
    monkeypatch.setattr(proactive_repository, "_rule_allows", lambda *args, **kwargs: (True, "due"))

    eligible = await proactive_repository.find_eligible_conversations(db)

    assert eligible == [bot_conv, oa_conv_a, oa_conv_b]
    assert calls == ["zalo_bot", "zalo_oa"]
