"""Application orchestration for durable outbound recovery."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class OutboundRecoveryCandidate:
    """One durable command selected for recovery."""

    outbox_id: int
    kind: Literal["pending", "stale_sending"]


@dataclass(frozen=True, slots=True)
class OutboundRecoverySummary:
    """Content-free recovery counters suitable for operational telemetry."""

    selected: int
    completed: int
    skipped: int
    failed: int


class OutboundRecoveryPort(Protocol):
    """Persistence/provider boundary required by the recovery use case."""

    async def pending_ids(self) -> Sequence[int]: ...

    async def stale_sending_ids(self) -> Sequence[int]: ...

    async def dispatch_pending(self, outbox_id: int) -> bool:
        """Dispatch and finalize a still-pending command."""
        ...

    async def terminalize_stale_sending(self, outbox_id: int) -> bool:
        """Finalize a stale in-flight command without resending it."""
        ...


RecoveryFailureHandler = Callable[[OutboundRecoveryCandidate, Exception], None]


async def recover_outbound_batch(
    port: OutboundRecoveryPort,
    *,
    on_failure: RecoveryFailureHandler | None = None,
) -> OutboundRecoverySummary:
    """Recover pending commands before stale sends, isolating item failures."""

    pending = [
        OutboundRecoveryCandidate(outbox_id=outbox_id, kind="pending")
        for outbox_id in await port.pending_ids()
    ]
    stale = [
        OutboundRecoveryCandidate(outbox_id=outbox_id, kind="stale_sending")
        for outbox_id in await port.stale_sending_ids()
    ]
    candidates = [*pending, *stale]
    completed = skipped = failed = 0

    for candidate in candidates:
        try:
            recovered = (
                await port.dispatch_pending(candidate.outbox_id)
                if candidate.kind == "pending"
                else await port.terminalize_stale_sending(candidate.outbox_id)
            )
            if recovered:
                completed += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001 - one command must not stop recovery
            failed += 1
            if on_failure is not None:
                on_failure(candidate, exc)

    return OutboundRecoverySummary(
        selected=len(candidates),
        completed=completed,
        skipped=skipped,
        failed=failed,
    )


__all__ = [
    "OutboundRecoveryCandidate",
    "OutboundRecoveryPort",
    "OutboundRecoverySummary",
    "recover_outbound_batch",
]
