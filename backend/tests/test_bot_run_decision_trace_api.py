from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api import bot_runs, conversations
from app.api.auth_dependencies import require_admin
from app.models.conversation import BotRunOutcome


def _route(path: str, method: str):
    routers = (bot_runs.router, conversations.router)
    return next(
        route
        for router in routers
        for route in router.routes
        if route.path == path and method in route.methods
    )


def test_trace_routes_are_admin_only() -> None:
    for path in ("/bot_runs/{run_id}", "/conversations/{conv_id}/bot-runs"):
        route = _route(path, "GET")
        assert any(dependency.call is require_admin for dependency in route.dependant.dependencies)


@pytest.mark.asyncio
async def test_conversation_trace_summary_is_a_lean_allowlist(monkeypatch) -> None:
    conversation_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    class _Service:
        def __init__(self, _db):
            pass

        async def list_conversation_trace_summaries(self, **_kwargs):
            return (
                [
                    {
                        "id": 9,
                        "conversation_id": conversation_id,
                        "started_at": now,
                        "ended_at": now,
                        "outcome": BotRunOutcome.SENT,
                        "trace_available": True,
                    }
                ],
                1,
            )

    async def _load(*_args, **_kwargs):
        return SimpleNamespace(id=conversation_id)

    monkeypatch.setattr(conversations, "BotRunService", _Service)
    monkeypatch.setattr(conversations, "_load", _load)

    response = await conversations.list_conversation_bot_runs(
        conversation_id,
        page=1,
        per_page=10,
        _admin=SimpleNamespace(),
        db=SimpleNamespace(),
    )
    payload = response.model_dump(mode="json")

    assert set(payload) == {"data", "total"}
    assert set(payload["data"][0]) == {
        "id",
        "conversation_id",
        "started_at",
        "ended_at",
        "outcome",
        "trace_available",
    }
    assert "proposed_reply" not in str(payload)
    assert "decision_trace" not in str(payload)


@pytest.mark.asyncio
async def test_detail_returns_only_sanitized_trace_contract(monkeypatch) -> None:
    conversation_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    class _Service:
        def __init__(self, _db):
            pass

        async def get_trace_detail(self, _run_id):
            return {
                "id": 9,
                "conversation_id": conversation_id,
                "started_at": now,
                "ended_at": now,
                "outcome": BotRunOutcome.SENT,
                "trace_available": True,
                "decision_trace": {
                    "version": 1,
                    "events": [
                        {
                            "seq": 1,
                            "kind": "tool",
                            "name": "search_knowledge",
                            "selected_by": "model",
                        }
                    ],
                    "truncated": False,
                },
            }

    monkeypatch.setattr(bot_runs, "BotRunService", _Service)
    payload = await bot_runs.get_bot_run_detail(
        9,
        _admin=SimpleNamespace(),
        db=SimpleNamespace(),
    )

    assert "proposed_reply" not in str(payload)
    assert payload["decision_trace"]["events"][0] == {
        "seq": 1,
        "kind": "tool",
        "name": "search_knowledge",
        "selected_by": "model",
    }
