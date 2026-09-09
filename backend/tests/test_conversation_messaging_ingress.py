from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.conversation_messaging.application.ingress import (
    InboundIdentity,
    InboundMessageUseCases,
    InboundTextCommand,
    PersistedInboundMessage,
    inbound_dedup_key,
)
from app.conversation_messaging.infrastructure.ingress import (
    SqlAlchemyInboundMessageAdapter,
)


def _command() -> InboundTextCommand:
    return InboundTextCommand(
        identity=InboundIdentity(
            provider="facebook_messenger",
            account_key="page-1",
            external_id="user-1",
        ),
        external_message_id="message-1",
        text="hello",
    )


def _persisted() -> PersistedInboundMessage:
    return PersistedInboundMessage(
        conversation_id="4c71935e-7a2b-4bd4-9d87-a9d152e2f199",
        message_id=17,
        body="hello",
        provider_message_id="message-1",
        created_at=datetime(2026, 7, 23, tzinfo=UTC),
    )


async def test_ingress_claims_before_persisting() -> None:
    calls: list[str] = []

    class Port:
        async def claim(self, command, dedup_key) -> bool:
            calls.append(f"claim:{dedup_key}")
            return True

        async def persist(self, command) -> PersistedInboundMessage | None:
            calls.append("persist")
            return _persisted()

    command = _command()
    result = await InboundMessageUseCases(Port()).ingest(command)

    assert calls == [f"claim:{inbound_dedup_key(command)}", "persist"]
    assert result.status == "persisted"
    assert result.conversation_id == _persisted().conversation_id
    assert result.message == _persisted()


async def test_ingress_stops_when_transient_claim_is_duplicate() -> None:
    class Port:
        async def claim(self, command, dedup_key) -> bool:
            return False

        async def persist(self, command) -> PersistedInboundMessage | None:
            raise AssertionError("duplicate claim must stop persistence")

    result = await InboundMessageUseCases(Port()).ingest(_command())

    assert result.status == "duplicate"


async def test_ingress_maps_durable_uniqueness_loss_to_duplicate() -> None:
    class Port:
        async def claim(self, command, dedup_key) -> bool:
            return True

        async def persist(self, command) -> PersistedInboundMessage | None:
            return None

    result = await InboundMessageUseCases(Port()).ingest(_command())

    assert result.status == "duplicate"


async def test_sqlalchemy_adapter_propagates_operational_persistence_failure(
    monkeypatch,
) -> None:
    conversation = SimpleNamespace(id=uuid.uuid4())

    class Service:
        def __init__(self, db) -> None:
            pass

        ensure_by_identity = AsyncMock(return_value=conversation)
        record_inbound = AsyncMock(side_effect=RuntimeError("database unavailable"))

    monkeypatch.setattr("app.services.conversation.ConversationService", Service)
    db = SimpleNamespace(refresh=AsyncMock(), rollback=AsyncMock())

    with pytest.raises(RuntimeError, match="database unavailable"):
        await SqlAlchemyInboundMessageAdapter(db).persist(_command())

    db.rollback.assert_not_awaited()


async def test_sqlalchemy_adapter_maps_only_integrity_error_to_duplicate(
    monkeypatch,
) -> None:
    conversation = SimpleNamespace(id=uuid.uuid4())

    class DuplicateViolation(Exception):
        sqlstate = "23505"
        constraint_name = "uq_messages_conv_provider_message"

    class Service:
        def __init__(self, db) -> None:
            pass

        ensure_by_identity = AsyncMock(return_value=conversation)
        record_inbound = AsyncMock(
            side_effect=IntegrityError("insert", {}, DuplicateViolation("unique"))
        )

    monkeypatch.setattr("app.services.conversation.ConversationService", Service)
    db = SimpleNamespace(refresh=AsyncMock(), rollback=AsyncMock())

    result = await SqlAlchemyInboundMessageAdapter(db).persist(_command())

    assert result is None
    db.rollback.assert_awaited_once()


@pytest.mark.parametrize(
    "sqlstate,constraint_name",
    [
        ("23503", "fk_messages_conversation_id"),
        ("23505", "uq_messages_other_field"),
    ],
)
async def test_sqlalchemy_adapter_propagates_other_integrity_failures(
    monkeypatch,
    sqlstate: str,
    constraint_name: str,
) -> None:
    conversation = SimpleNamespace(id=uuid.uuid4())

    class OtherViolation(Exception):
        pass

    violation = OtherViolation("integrity failure")
    violation.sqlstate = sqlstate
    violation.constraint_name = constraint_name

    class Service:
        def __init__(self, db) -> None:
            pass

        ensure_by_identity = AsyncMock(return_value=conversation)
        record_inbound = AsyncMock(
            side_effect=IntegrityError("insert", {}, violation)
        )

    monkeypatch.setattr("app.services.conversation.ConversationService", Service)
    db = SimpleNamespace(refresh=AsyncMock(), rollback=AsyncMock())

    with pytest.raises(IntegrityError):
        await SqlAlchemyInboundMessageAdapter(db).persist(_command())

    db.rollback.assert_awaited_once()


def test_conversation_service_exposes_the_methods_the_adapter_calls():
    """The adapter drives the real ConversationService, not just a stub.

    Every test above substitutes a fake service, so a method the adapter calls
    can go missing from the real class without a single failure. That happened:
    ``ensure_by_identity`` lived only on ConversationState, so every Messenger
    event died with AttributeError while the suite stayed green.
    """
    import inspect

    from app.services.conversation import ConversationService

    for name in ("ensure_by_identity", "record_inbound"):
        method = getattr(ConversationService, name, None)
        assert method is not None, f"ConversationService is missing {name}()"
        assert inspect.iscoroutinefunction(method), f"{name}() must be awaitable"

    signature = inspect.signature(ConversationService.ensure_by_identity)
    assert {
        "provider",
        "account_key",
        "external_id",
    } <= set(signature.parameters)
