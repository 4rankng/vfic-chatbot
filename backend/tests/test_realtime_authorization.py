from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.models.user import Role
from app.realtime import socketio as socketio_module
from app.services.viewer_scope import (
    viewer_can_access_conversation,
    viewer_can_access_lead,
)


@pytest.fixture(autouse=True)
def clear_socket_access_state() -> None:
    socketio_module._connection_access.clear()


def _access(sid: str = "sid-1") -> socketio_module._ConnectionAccess:
    access = socketio_module._ConnectionAccess(id=uuid4(), role=Role.recruiter)
    socketio_module._connection_access[sid] = access
    return access


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("access_check", "entity_id"),
    [
        (viewer_can_access_conversation, UUID("00000000-0000-4000-8000-000000000001")),
        (viewer_can_access_lead, 1),
    ],
)
@pytest.mark.parametrize(("role", "has_scope"), [(Role.admin, False), (Role.recruiter, True)])
async def test_entity_access_checks_apply_the_canonical_viewer_scope(
    access_check, entity_id: UUID | int, role: Role, has_scope: bool
) -> None:
    class CapturingDb:
        statement = None

        async def scalar(self, statement):
            self.statement = statement
            return entity_id

    db = CapturingDb()
    viewer = SimpleNamespace(id=uuid4(), role=role)

    assert await access_check(db, entity_id, viewer) is True
    sql = str(db.statement)
    assert ("assigned_recruiter_id" in sql) is has_scope


@pytest.mark.parametrize("value", [None, "", "not-a-uuid", 1, True, {}, []])
def test_conversation_id_rejects_malformed_values(value: object) -> None:
    assert socketio_module._conversation_id(value) is None


def test_conversation_id_canonicalizes_uuid_strings() -> None:
    conversation_id = uuid4()
    assert socketio_module._conversation_id(str(conversation_id)) == conversation_id


@pytest.mark.parametrize("value", [None, 0, -1, True, False, "1", 1.5, {}, []])
def test_lead_id_requires_a_positive_integer(value: object) -> None:
    assert socketio_module._lead_id(value) is None


def test_lead_id_accepts_a_positive_integer() -> None:
    assert socketio_module._lead_id(7) == 7


@pytest.mark.asyncio
async def test_authorization_uses_authenticated_viewer_and_fails_closed(monkeypatch) -> None:
    access = _access()
    db = SimpleNamespace()

    @asynccontextmanager
    async def fake_async_session() -> AsyncIterator[object]:
        yield db

    import app.core.db as db_module

    check = AsyncMock(return_value=True)
    monkeypatch.setattr(db_module, "async_session", fake_async_session)
    monkeypatch.setattr(socketio_module, "viewer_can_access_conversation", check)

    conversation_id = uuid4()
    assert await socketio_module._authorize_entity("sid-1", "conv", conversation_id) is access
    check.assert_awaited_once_with(db, conversation_id, access)

    check.side_effect = RuntimeError("database unavailable")
    assert await socketio_module._authorize_entity("sid-1", "conv", conversation_id) is None


@pytest.mark.asyncio
async def test_conversation_join_enters_room_only_after_authorization(monkeypatch) -> None:
    access = _access()
    conversation_id = uuid4()
    authorize = AsyncMock(return_value=access)
    enter_room = AsyncMock()
    monkeypatch.setattr(socketio_module, "_authorize_entity", authorize)
    monkeypatch.setattr(socketio_module.sio, "enter_room", enter_room)

    await socketio_module._join_conversation("sid-1", {"conversation_id": str(conversation_id)})

    authorize.assert_awaited_once_with("sid-1", "conv", conversation_id)
    enter_room.assert_awaited_once_with("sid-1", f"conv:{conversation_id}")
    assert access.rooms == {f"conv:{conversation_id}"}


@pytest.mark.asyncio
async def test_conversation_join_denial_has_no_room_side_effect(monkeypatch) -> None:
    enter_room = AsyncMock()
    monkeypatch.setattr(socketio_module, "_authorize_entity", AsyncMock(return_value=None))
    monkeypatch.setattr(socketio_module.sio, "enter_room", enter_room)

    await socketio_module._join_conversation("sid-1", {"conversation_id": str(uuid4())})

    enter_room.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_join_ids_do_not_run_authorization_or_room_mutations(monkeypatch) -> None:
    authorize = AsyncMock()
    enter_room = AsyncMock()
    monkeypatch.setattr(socketio_module, "_authorize_entity", authorize)
    monkeypatch.setattr(socketio_module.sio, "enter_room", enter_room)

    await socketio_module._join_conversation("sid-1", {"conversation_id": "bad"})
    await socketio_module._join_lead("sid-1", {"lead_id": 0})

    authorize.assert_not_awaited()
    enter_room.assert_not_awaited()


@pytest.mark.asyncio
async def test_lead_join_and_tracked_leave_are_authorized(monkeypatch) -> None:
    access = _access()
    authorize = AsyncMock(return_value=access)
    enter_room = AsyncMock()
    leave_room = AsyncMock()
    monkeypatch.setattr(socketio_module, "_authorize_entity", authorize)
    monkeypatch.setattr(socketio_module.sio, "enter_room", enter_room)
    monkeypatch.setattr(socketio_module.sio, "leave_room", leave_room)

    await socketio_module._join_lead("sid-1", {"lead_id": 17})
    await socketio_module._leave_lead("sid-1", {"lead_id": 17})
    await socketio_module._leave_lead("sid-1", {"lead_id": 18})

    authorize.assert_awaited_once_with("sid-1", "lead", 17)
    enter_room.assert_awaited_once_with("sid-1", "lead:17")
    leave_room.assert_awaited_once_with("sid-1", "lead:17")
    assert access.rooms == set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "service_name", "data", "expected_type", "expected_id"),
    [
        ("_presence_join", "join_viewing", {"entity_type": "lead", "entity_id": 9}, "lead", 9),
        (
            "_presence_heartbeat",
            "heartbeat_viewing",
            {"entity_type": "lead", "entity_id": 9},
            "lead",
            9,
        ),
        (
            "_presence_typing",
            "start_typing",
            {"entity_type": "conv", "entity_id": "00000000-0000-4000-8000-000000000009"},
            "conv",
            UUID("00000000-0000-4000-8000-000000000009"),
        ),
    ],
)
async def test_presence_active_mutations_authorize_before_side_effect(
    monkeypatch,
    handler_name: str,
    service_name: str,
    data: dict,
    expected_type: str,
    expected_id: UUID | int,
) -> None:
    from app.services import presence

    access = _access()
    authorize = AsyncMock(return_value=access)
    service = AsyncMock()
    monkeypatch.setattr(socketio_module, "_authorize_entity", authorize)
    monkeypatch.setattr(presence, service_name, service)

    await getattr(socketio_module, handler_name)("sid-1", data)

    authorize.assert_awaited_once_with("sid-1", expected_type, expected_id)
    canonical_id = str(expected_id)
    expected_service_id = canonical_id if service_name == "start_typing" else expected_id
    service.assert_awaited_once_with(expected_type, expected_service_id, str(access.id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "service_name", "data"),
    [
        ("_presence_join", "join_viewing", {"entity_type": "lead", "entity_id": 9}),
        (
            "_presence_heartbeat",
            "heartbeat_viewing",
            {"entity_type": "lead", "entity_id": 9},
        ),
        (
            "_presence_typing",
            "start_typing",
            {"entity_type": "conv", "entity_id": "00000000-0000-4000-8000-000000000009"},
        ),
    ],
)
async def test_presence_denial_has_zero_service_side_effects(
    monkeypatch, handler_name: str, service_name: str, data: dict
) -> None:
    from app.services import presence

    service = AsyncMock()
    monkeypatch.setattr(socketio_module, "_authorize_entity", AsyncMock(return_value=None))
    monkeypatch.setattr(presence, service_name, service)

    await getattr(socketio_module, handler_name)("sid-1", data)

    service.assert_not_awaited()


@pytest.mark.asyncio
async def test_arbitrary_presence_type_is_rejected_before_authorization(monkeypatch) -> None:
    from app.services import presence

    authorize = AsyncMock()
    join_viewing = AsyncMock()
    monkeypatch.setattr(socketio_module, "_authorize_entity", authorize)
    monkeypatch.setattr(presence, "join_viewing", join_viewing)

    await socketio_module._presence_join(
        "sid-1", {"entity_type": "user", "entity_id": str(uuid4())}
    )

    authorize.assert_not_awaited()
    join_viewing.assert_not_awaited()


@pytest.mark.asyncio
async def test_presence_leave_and_stop_typing_require_tracked_authorization(monkeypatch) -> None:
    from app.services import presence

    access = _access()
    conversation_id = uuid4()
    access.presence_entities.add(("lead", "4"))
    access.typing_entities.add(("conv", str(conversation_id)))
    leave_viewing = AsyncMock()
    stop_typing = AsyncMock()
    authorize = AsyncMock(return_value=access)
    monkeypatch.setattr(presence, "leave_viewing", leave_viewing)
    monkeypatch.setattr(presence, "stop_typing", stop_typing)
    monkeypatch.setattr(socketio_module, "_authorize_entity", authorize)

    await socketio_module._presence_leave("sid-1", {"entity_type": "lead", "entity_id": 4})
    await socketio_module._presence_stop_typing(
        "sid-1", {"entity_type": "conv", "entity_id": str(conversation_id)}
    )
    await socketio_module._presence_leave("sid-1", {"entity_type": "lead", "entity_id": 5})

    leave_viewing.assert_awaited_once_with("lead", 4, str(access.id))
    authorize.assert_awaited_once_with("sid-1", "conv", conversation_id)
    stop_typing.assert_awaited_once_with("conv", str(conversation_id), str(access.id))
    assert access.presence_entities == set()
    assert access.typing_entities == set()


@pytest.mark.asyncio
async def test_disconnect_cleans_tracked_presence_and_typing(monkeypatch) -> None:
    from app.services import presence

    access = _access()
    conversation_id = uuid4()
    access.presence_entities.update({("lead", "3"), ("conv", str(conversation_id))})
    access.typing_entities.add(("conv", str(conversation_id)))
    leave_viewing = AsyncMock()
    stop_typing = AsyncMock()
    monkeypatch.setattr(presence, "leave_viewing", leave_viewing)
    monkeypatch.setattr(presence, "stop_typing", stop_typing)

    await socketio_module.disconnect("sid-1")

    assert "sid-1" not in socketio_module._connection_access
    assert leave_viewing.await_count == 2
    leave_viewing.assert_any_await("lead", 3, str(access.id))
    leave_viewing.assert_any_await("conv", conversation_id, str(access.id))
    stop_typing.assert_awaited_once_with("conv", str(conversation_id), str(access.id))


def test_room_routing_requires_valid_entity_ids() -> None:
    conversation_id = uuid4()
    assert socketio_module._room_for_payload({"conversation_id": str(conversation_id)}) == (
        f"conv:{conversation_id}"
    )
    assert socketio_module._room_for_payload({"lead_id": 8}) == "lead:8"
    assert socketio_module._room_for_payload({}) is None
    assert socketio_module._room_for_payload({"id": "not-a-uuid"}) is None
    assert socketio_module._room_for_payload({"lead_id": "8"}) is None


@pytest.mark.asyncio
async def test_unroutable_publish_is_suppressed_instead_of_broadcast(monkeypatch) -> None:
    from app.realtime import emitter
    from app.services.realtime import publish_event

    emit_event = AsyncMock()
    monkeypatch.setattr(emitter, "emit_event", emit_event)

    await publish_event("unsafe.event", {"status": "changed"})

    emit_event.assert_not_awaited()
