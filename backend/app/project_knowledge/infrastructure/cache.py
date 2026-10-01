"""Current best-effort cache repair adapter."""

from __future__ import annotations

from app.core.cache import bump_cache_version, bump_kb_caches
from app.core.preamble_cache import NS_PREAMBLE


class RedisProjectKnowledgeCacheRepair:
    async def repair_knowledge_and_jobs(self) -> None:
        # Preserve the established post-commit order and best-effort behavior.
        await bump_kb_caches()
        await bump_cache_version("jobs")
        await bump_cache_version(NS_PREAMBLE)


__all__ = ["RedisProjectKnowledgeCacheRepair"]
