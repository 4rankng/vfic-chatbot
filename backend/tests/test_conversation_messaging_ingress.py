from __future__ import annotations

from app.conversation_messaging.application.ingress import (
    InboundIdentity,
    InboundMessageUseCases,
    InboundTextCommand,
    inbound_dedup_key,
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


async def test_ingress_claims_before_persisting() -> None:
    calls: list[str] = []

    class Port:
        async def claim(self, command, dedup_key) -> bool:
            calls.append(f"claim:{dedup_key}")
            return True

        async def persist(self, command) -> str | None:
            calls.append("persist")
            return "conversation-1"

    command = _command()
    result = await InboundMessageUseCases(Port()).ingest(command)

    assert calls == [f"claim:{inbound_dedup_key(command)}", "persist"]
    assert result.status == "persisted"
    assert result.conversation_id == "conversation-1"


async def test_ingress_stops_when_transient_claim_is_duplicate() -> None:
    class Port:
        async def claim(self, command, dedup_key) -> bool:
            return False

        async def persist(self, command) -> str | None:
            raise AssertionError("duplicate claim must stop persistence")

    result = await InboundMessageUseCases(Port()).ingest(_command())

    assert result.status == "duplicate"


async def test_ingress_maps_durable_uniqueness_loss_to_duplicate() -> None:
    class Port:
        async def claim(self, command, dedup_key) -> bool:
            return True

        async def persist(self, command) -> str | None:
            return None

    result = await InboundMessageUseCases(Port()).ingest(_command())

    assert result.status == "duplicate"
