"""Version-aware cache key resolution (Tech-Lead Directive §6).

Centralizes the cache-key shape so the exact cache, semantic cache, and
single-flight primitive all derive from one source of truth. The directive
requires the key to include: tenant_id, language, normalized_query,
active_job_id, active_company_id, candidate_segment (if relevant),
knowledge_version.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class CacheKey:
    """The resolved cache key for one (query, context) pair.

    Frozen + hashable so it can be used as a dict key (single-flight coalescing).
    Two turns with the same CacheKey share a cache entry AND a single-flight
    leader; two turns differing on any dimension get separate keys.
    """

    tenant_id: str
    knowledge_version: str
    active_job_id: str | None
    active_company_id: str | None
    language: str
    query_hash: str

    def to_string(self) -> str:
        """The Redis key string. Stable across processes."""
        return (
            f"answer:v2:{self.tenant_id}:{self.knowledge_version}:"
            f"{self.active_job_id or '-'}:{self.active_company_id or '-'}:"
            f"{self.language}:{self.query_hash}"
        )


def normalize_query(query: str) -> str:
    """Normalize a user query for cache-key hashing.

    Lowercases, strips whitespace, collapses internal whitespace. Vietnamese
    diacritics are PRESERVED (stripping them would conflate distinct queries).
    """
    import unicodedata

    nfc = unicodedata.normalize("NFC", query.strip().lower())
    return " ".join(nfc.split())


def resolve_cache_key(
    *,
    query: str,
    knowledge_version: str,
    active_job_id: str | None = None,
    active_company_id: str | None = None,
    language: str = "vi",
    tenant_id: str = "default",
) -> CacheKey:
    """Build a CacheKey from a turn's context. The single source of truth."""
    normalized = normalize_query(query)
    query_hash = sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return CacheKey(
        tenant_id=tenant_id,
        knowledge_version=str(knowledge_version),
        active_job_id=active_job_id,
        active_company_id=active_company_id,
        language=language,
        query_hash=query_hash,
    )
