"""Application boundary for deferred candidate persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PersistCandidateCommand:
    chat_id: str
    user_text: str
    bot_output: str
    expected_conversation_version: int | None = None


class CandidatePersistencePort(Protocol):
    async def persist(
        self,
        command: PersistCandidateCommand,
        *,
        embed_batch: Any,
        extractor: Any,
    ) -> Any: ...


async def persist_candidate(
    port: CandidatePersistencePort,
    command: PersistCandidateCommand,
    *,
    embed_batch: Any,
    extractor: Any,
) -> Any:
    """Persist one extracted candidate result through the injected adapter."""

    return await port.persist(
        command,
        embed_batch=embed_batch,
        extractor=extractor,
    )


__all__ = [
    "CandidatePersistencePort",
    "PersistCandidateCommand",
    "persist_candidate",
]
