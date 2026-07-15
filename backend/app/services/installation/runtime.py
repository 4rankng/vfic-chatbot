"""Best-effort cache for immutable active authority fingerprints."""

from __future__ import annotations

import uuid

from app.core.cache import bump_cache_version, cache_get_json, cache_set_json, cache_version
from app.services.installation.authority import RuntimeAuthorityFingerprint

INSTALLATION_CACHE_NAMESPACE = "installation_authority"
_ACTIVE_FINGERPRINT_TTL_SECONDS = 600


async def get_cached_fingerprint(
    revision_id: uuid.UUID, authority_generation: int
) -> RuntimeAuthorityFingerprint | None:
    version = await cache_version(INSTALLATION_CACHE_NAMESPACE)
    payload = await cache_get_json(_cache_key(version, revision_id, authority_generation))
    if not isinstance(payload, dict):
        return None
    try:
        return RuntimeAuthorityFingerprint(
            authority_generation=int(payload["authority_generation"]),
            revision_id=uuid.UUID(str(payload["revision_id"])),
            manifest_checksum=str(payload["manifest_checksum"]),
            pack_contract_hash=str(payload["pack_contract_hash"]),
            persona_checksum=str(payload["persona_checksum"]),
            workflow_policy_checksum=str(payload["workflow_policy_checksum"]),
            provider_policy_checksum=str(payload["provider_policy_checksum"]),
            template_checksums={
                str(key): str(value) for key, value in dict(payload["template_checksums"]).items()
            },
            active_kb_vector=tuple(
                (str(item[0]), str(item[1])) for item in payload["active_kb_vector"]
            ),
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return None


async def cache_fingerprint(fingerprint: RuntimeAuthorityFingerprint) -> None:
    version = await cache_version(INSTALLATION_CACHE_NAMESPACE)
    await cache_set_json(
        _cache_key(version, fingerprint.revision_id, fingerprint.authority_generation),
        fingerprint.canonical_payload(),
        ttl_seconds=_ACTIVE_FINGERPRINT_TTL_SECONDS,
    )


async def invalidate_installation_cache() -> None:
    await bump_cache_version(INSTALLATION_CACHE_NAMESPACE)


def _cache_key(version: str, revision_id: uuid.UUID, authority_generation: int) -> str:
    return f"installation:active:v{version}:{revision_id}:{authority_generation}"
