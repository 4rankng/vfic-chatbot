from __future__ import annotations

from app.conversation_messaging.application.outbound_recovery import (
    OutboundRecoveryCandidate,
    recover_outbound_batch,
)


class _RecoveryFake:
    def __init__(self) -> None:
        self.seen: list[OutboundRecoveryCandidate] = []

    async def pending_ids(self) -> list[int]:
        return [3, 4]

    async def stale_sending_ids(self) -> list[int]:
        return [8, 9]

    async def dispatch_pending(self, outbox_id: int) -> bool:
        self.seen.append(OutboundRecoveryCandidate(outbox_id, "pending"))
        if outbox_id == 4:
            return False
        return True

    async def terminalize_stale_sending(self, outbox_id: int) -> bool:
        self.seen.append(OutboundRecoveryCandidate(outbox_id, "stale_sending"))
        if outbox_id == 8:
            raise RuntimeError("provider unavailable")
        return True


async def test_recovery_orders_pending_before_stale_and_isolates_failures() -> None:
    fake = _RecoveryFake()
    failures: list[tuple[OutboundRecoveryCandidate, str]] = []

    summary = await recover_outbound_batch(
        fake,
        on_failure=lambda candidate, error: failures.append((candidate, str(error))),
    )

    assert fake.seen == [
        OutboundRecoveryCandidate(3, "pending"),
        OutboundRecoveryCandidate(4, "pending"),
        OutboundRecoveryCandidate(8, "stale_sending"),
        OutboundRecoveryCandidate(9, "stale_sending"),
    ]
    assert failures == [
        (OutboundRecoveryCandidate(8, "stale_sending"), "provider unavailable")
    ]
    assert summary.selected == 4
    assert summary.completed == 2
    assert summary.skipped == 1
    assert summary.failed == 1


async def test_recovery_empty_batch_is_a_noop() -> None:
    class EmptyFake:
        async def pending_ids(self) -> list[int]:
            return []

        async def stale_sending_ids(self) -> list[int]:
            return []

        async def dispatch_pending(self, outbox_id: int) -> bool:
            raise AssertionError(outbox_id)

        async def terminalize_stale_sending(self, outbox_id: int) -> bool:
            raise AssertionError(outbox_id)

    summary = await recover_outbound_batch(EmptyFake())

    assert summary.selected == 0
    assert summary.completed == 0
    assert summary.skipped == 0
    assert summary.failed == 0


async def test_stale_candidate_is_terminalized_without_pending_dispatch() -> None:
    calls: list[tuple[str, int]] = []

    class StaleOnlyFake:
        async def pending_ids(self) -> list[int]:
            return []

        async def stale_sending_ids(self) -> list[int]:
            return [12]

        async def dispatch_pending(self, outbox_id: int) -> bool:
            calls.append(("dispatch", outbox_id))
            return True

        async def terminalize_stale_sending(self, outbox_id: int) -> bool:
            calls.append(("terminalize", outbox_id))
            return True

    summary = await recover_outbound_batch(StaleOnlyFake())

    assert calls == [("terminalize", 12)]
    assert summary.completed == 1
