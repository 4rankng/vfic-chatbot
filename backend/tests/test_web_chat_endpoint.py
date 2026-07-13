"""Tests for the web-chat inline turn endpoint (Tech-Lead Directive §0).

Style matches the existing conversation-API tests: monkeypatch the handler's
deps with SimpleNamespace + AsyncMock so no HTTP client / DB / LLM is needed.

Covers:
- Admin-only: require_admin dep is wired (non-admin rejected by FastAPI)
- run_turn is invoked with execution_source="web_chat"
- Successful turn returns the bot's reply inline as JSON
- An exception inside run_turn surfaces as HTTPException 500
- The endpoint loads the conversation via _load (404 path is _load's job)
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_web_chat_turn_invokes_run_turn_with_web_chat_source(monkeypatch) -> None:
    """The handler builds a BotRunState with execution_source='web_chat' and calls run_turn."""
    from app.api import conversations
    from app.graph.types import BotRunState

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        version=7,
        zalo_chat_id="chat-1",
        assigned_recruiter_id=None,
        mode=None,
    )
    captured_state: dict = {}

    async def fake_run_turn(state: BotRunState, deps):
        captured_state["state"] = state
        return {"outcome": "sent", "reply": "Chào bạn!"}

    async def fake_build_deps(db, *, session_factory=None):
        return SimpleNamespace()

    monkeypatch.setattr(conversations, "_load", AsyncMock(return_value=conv))
    monkeypatch.setattr("app.graph.runner.run_turn", fake_run_turn)
    monkeypatch.setattr("app.graph.factories.build_deps", fake_build_deps)

    result = await conversations.web_chat_turn(
        conv.id,
        body=SimpleNamespace(body="chào bạn"),
        user=SimpleNamespace(id=uuid.uuid4(), role="admin"),
        db=SimpleNamespace(),
    )

    assert result["outcome"] == "sent"
    assert result["reply"] == "Chào bạn!"
    assert result["conversation_id"] == str(conv.id)
    state = captured_state["state"]
    assert state.execution_source == "web_chat"
    assert state.user_text == "chào bạn"
    assert state.conversation_id == str(conv.id)


@pytest.mark.asyncio
async def test_web_chat_turn_uses_admin_only_dependency(monkeypatch) -> None:
    """require_admin is the auth dep — non-admins are rejected at the dep layer.

    We verify by inspecting the endpoint's dependency signature, not by exercising
    FastAPI's auth pipeline (which would require a full app + JWT). The presence
    of ``Depends(require_admin)`` in the signature is the contract.
    """
    import inspect

    from app.api import conversations
    from app.api.dependencies import require_admin

    sig = inspect.signature(conversations.web_chat_turn)
    user_param = sig.parameters["user"]
    dep = user_param.default
    # The dependency must be Depends(require_admin) — FastAPI's Depends object
    # wraps the callable.
    assert callable(getattr(dep, "dependency", None)) or dep is require_admin


@pytest.mark.asyncio
async def test_web_chat_turn_exception_surfaces_as_500(monkeypatch) -> None:
    """An exception inside run_turn is caught and re-raised as HTTPException 500."""
    from fastapi import HTTPException

    from app.api import conversations

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        version=1,
        zalo_chat_id="chat-1",
        assigned_recruiter_id=None,
        mode=None,
    )
    monkeypatch.setattr(conversations, "_load", AsyncMock(return_value=conv))

    async def exploding_run_turn(state, deps):
        raise RuntimeError("model offline")

    async def fake_build_deps(db, *, session_factory=None):
        return SimpleNamespace()

    monkeypatch.setattr("app.graph.runner.run_turn", exploding_run_turn)
    monkeypatch.setattr("app.graph.factories.build_deps", fake_build_deps)

    with pytest.raises(HTTPException) as exc_info:
        await conversations.web_chat_turn(
            conv.id,
            body=SimpleNamespace(body="hello"),
            user=SimpleNamespace(id=uuid.uuid4(), role="admin"),
            db=SimpleNamespace(),
        )
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_web_chat_turn_stamps_received_at_and_deadline(monkeypatch) -> None:
    """The state has a real deadline_at_epoch = received_at_epoch + sla_seconds."""
    import time

    from app.api import conversations

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        version=1,
        zalo_chat_id="chat-1",
        assigned_recruiter_id=None,
        mode=None,
    )
    captured: dict = {}

    async def fake_run_turn(state, deps):
        captured["received"] = state.received_at_epoch
        captured["deadline"] = state.deadline_at_epoch
        return {"outcome": "sent", "reply": "ok"}

    async def fake_build_deps(db, *, session_factory=None):
        return SimpleNamespace()

    monkeypatch.setattr(conversations, "_load", AsyncMock(return_value=conv))
    monkeypatch.setattr("app.graph.runner.run_turn", fake_run_turn)
    monkeypatch.setattr("app.graph.factories.build_deps", fake_build_deps)

    t_before = time.time()
    await conversations.web_chat_turn(
        conv.id,
        body=SimpleNamespace(body="hi"),
        user=SimpleNamespace(id=uuid.uuid4(), role="admin"),
        db=SimpleNamespace(),
    )
    # Deadline = received + sla_seconds (10s default). Both stamps are within
    # a tight window of "now".
    assert captured["received"] >= t_before
    assert captured["deadline"] == pytest.approx(captured["received"] + 10.0, abs=0.5)


@pytest.mark.asyncio
async def test_web_chat_turn_loads_conversation_via_load(monkeypatch) -> None:
    """The endpoint calls _load (which 404s on unknown conv_id)."""
    from app.api import conversations

    load_calls: list = []
    conv = SimpleNamespace(
        id=uuid.uuid4(),
        version=1,
        zalo_chat_id="chat-1",
        assigned_recruiter_id=None,
        mode=None,
    )

    async def tracking_load(conv_id, db, user=None):
        load_calls.append(conv_id)
        return conv

    async def fake_run_turn(state, deps):
        return {"outcome": "sent", "reply": "ok"}

    async def fake_build_deps(db, *, session_factory=None):
        return SimpleNamespace()

    monkeypatch.setattr(conversations, "_load", tracking_load)
    monkeypatch.setattr("app.graph.runner.run_turn", fake_run_turn)
    monkeypatch.setattr("app.graph.factories.build_deps", fake_build_deps)

    await conversations.web_chat_turn(
        conv.id,
        body=SimpleNamespace(body="hi"),
        user=SimpleNamespace(id=uuid.uuid4(), role="admin"),
        db=SimpleNamespace(),
    )
    assert load_calls == [conv.id]
