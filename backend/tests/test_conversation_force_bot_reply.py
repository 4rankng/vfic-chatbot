"""POST /conversations/{id}/force-bot-reply — the recruiter's bot nudge.

The lever for the two shapes that leave a candidate hanging without a
takeover: an ad-prefill thread the bot skipped (Meta's closed window), and a
turn that died before its reply went out. Drives the real route on a bare
app with the collaborators faked.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import conversations as conversations_api
from app.api.auth_dependencies import get_current_user
from app.conversation_messaging.domain.statuses import (
    ConversationMode,
    ConversationStatus,
)
from app.shared.infrastructure.db import get_request_db

_CONV_ID = uuid.uuid4()


def _client(conv: SimpleNamespace) -> TestClient:
    from app.core.errors import register_domain_exception_handlers

    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(conversations_api.router, prefix="/api/v1")
    app.dependency_overrides[get_request_db] = lambda: SimpleNamespace()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())

    async def _load(_conv_id, _db, _user):
        return conv

    conversations_api._load = _load  # type: ignore[method-assign]
    return TestClient(app)


@pytest.fixture
def bot_conv():
    from datetime import UTC, datetime

    from app.models.conversation import Conversation

    conv = Conversation(
        zalo_chat_id="fb-force-bot-reply",
        zalo_channel="facebook_messenger",
        mode=ConversationMode.BOT,
        status=ConversationStatus.OPEN,
        needs_human=False,
        unread_count=0,
        project_context_state="EXPLORE",
        version=7,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    conv.id = _CONV_ID
    return conv


@pytest.fixture(autouse=True)
def _restore_load():
    original = conversations_api._load
    yield
    conversations_api._load = original  # type: ignore[method-assign]


def _patch_flow(monkeypatch, *, enqueued: bool, cleared: list):
    class FakeService:
        def __init__(self, _db) -> None:
            pass

        async def clear_ad_entry_prefill_flag(self, conversation_id):
            cleared.append(conversation_id)
            return True

    monkeypatch.setattr(conversations_api, "ConversationService", FakeService)

    async def _enqueue(_svc, _conv, *, enqueue):
        assert callable(enqueue)
        return enqueued

    monkeypatch.setattr(
        conversations_api, "enqueue_latest_unanswered_worker_message", _enqueue
    )


def test_force_bot_reply_clears_the_flag_and_enqueues_the_pending_turn(
    monkeypatch, bot_conv
) -> None:
    cleared: list = []
    _patch_flow(monkeypatch, enqueued=True, cleared=cleared)

    response = _client(bot_conv).post(f"/api/v1/conversations/{_CONV_ID}/force-bot-reply")

    assert response.status_code == 200
    assert cleared == [_CONV_ID]


def test_force_bot_reply_reports_when_no_candidate_message_is_waiting(
    monkeypatch, bot_conv
) -> None:
    cleared: list = []
    _patch_flow(monkeypatch, enqueued=False, cleared=cleared)

    response = _client(bot_conv).post(f"/api/v1/conversations/{_CONV_ID}/force-bot-reply")

    assert response.status_code == 409
    assert "đang chờ" in response.json()["detail"]


def test_force_bot_reply_refuses_a_taken_over_thread(monkeypatch, bot_conv) -> None:
    cleared: list = []
    _patch_flow(monkeypatch, enqueued=True, cleared=cleared)
    bot_conv.mode = ConversationMode.HUMAN

    response = _client(bot_conv).post(f"/api/v1/conversations/{_CONV_ID}/force-bot-reply")

    assert response.status_code == 409
    assert "nhân viên" in response.json()["detail"]
    assert cleared == []
