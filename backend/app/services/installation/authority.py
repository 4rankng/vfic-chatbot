"""Canonical authority fingerprint carried across runtime boundaries."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeAuthorityFingerprint:
    authority_generation: int
    revision_id: uuid.UUID
    manifest_checksum: str
    pack_contract_hash: str
    persona_checksum: str
    workflow_policy_checksum: str
    provider_policy_checksum: str
    template_checksums: dict[str, str]
    active_kb_vector: tuple[tuple[str, str], ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "authority_generation": self.authority_generation,
            "revision_id": str(self.revision_id),
            "manifest_checksum": self.manifest_checksum,
            "pack_contract_hash": self.pack_contract_hash,
            "persona_checksum": self.persona_checksum,
            "workflow_policy_checksum": self.workflow_policy_checksum,
            "provider_policy_checksum": self.provider_policy_checksum,
            "template_checksums": dict(sorted(self.template_checksums.items())),
            "active_kb_vector": [list(item) for item in sorted(self.active_kb_vector)],
        }

    def checksum(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
