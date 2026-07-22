"""Cache-repair port for committed project/knowledge authority."""

from __future__ import annotations

from typing import Protocol


class ProjectKnowledgeCacheRepairPort(Protocol):
    async def repair_knowledge_and_jobs(self) -> None: ...


__all__ = ["ProjectKnowledgeCacheRepairPort"]

