"""Closed-world registry of code-reviewed industry packs and capabilities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from app.capabilities.contracts import CapabilityDefinition, IndustryPackDefinition
from app.capabilities.recruitment.definition import CAPABILITIES as RECRUITMENT_CAPABILITIES
from app.capabilities.recruitment.definition import PACK as RECRUITMENT_PACK


class CapabilityRegistry:
    def __init__(
        self,
        *,
        capabilities: Iterable[CapabilityDefinition],
        packs: Iterable[IndustryPackDefinition],
    ) -> None:
        self._capabilities = self._unique_by_id(capabilities, "capability_id")
        self._packs = self._unique_by_id(packs, "key")
        for pack in self._packs.values():
            self.validate_selection(pack.key, pack.capability_ids)

    @staticmethod
    def _unique_by_id(items: Iterable[object], attribute: str) -> dict[str, object]:
        indexed: dict[str, object] = {}
        for item in items:
            key = str(getattr(item, attribute))
            if key in indexed:
                raise ValueError(f"duplicate registry key: {key}")
            indexed[key] = item
        return indexed

    def get_pack(self, key: str) -> IndustryPackDefinition:
        try:
            pack = self._packs[key]
        except KeyError as exc:
            raise ValueError(f"unknown industry pack: {key}") from exc
        return pack  # type: ignore[return-value]

    def packs(self) -> tuple[IndustryPackDefinition, ...]:
        return tuple(self._packs[key] for key in sorted(self._packs))  # type: ignore[return-value]

    def capabilities(self) -> tuple[CapabilityDefinition, ...]:
        return tuple(
            self._capabilities[key] for key in sorted(self._capabilities)
        )  # type: ignore[return-value]

    def validate_selection(self, pack_key: str, capability_ids: Iterable[str]) -> tuple[str, ...]:
        pack = self.get_pack(pack_key)
        selected = tuple(sorted(set(capability_ids)))
        unknown = set(selected) - set(pack.capability_ids)
        if unknown:
            raise ValueError(f"capabilities are not in pack {pack_key}: {sorted(unknown)}")
        for capability_id in selected:
            capability = self._capabilities.get(capability_id)
            if capability is None:
                raise ValueError(f"unknown capability: {capability_id}")
            missing = set(capability.dependencies) - set(selected)  # type: ignore[attr-defined]
            if missing:
                raise ValueError(f"capability {capability_id} requires: {sorted(missing)}")
        return selected

    def pack_contract_hash(self, pack_key: str) -> str:
        """Hash only the selected pack contract, not unrelated registry entries."""
        pack = self.get_pack(pack_key)
        capabilities = []
        for capability_id in sorted(pack.capability_ids):
            capability = self._capabilities[capability_id]
            capabilities.append(
                {
                    "id": capability.capability_id,  # type: ignore[attr-defined]
                    "dependencies": sorted(capability.dependencies),  # type: ignore[attr-defined]
                }
            )
        payload = {
            "key": pack.key,
            "version": pack.version,
            "kernel_abi": pack.kernel_abi,
            "compatible_operational_data": sorted(pack.compatible_operational_data),
            "workflow_ids": sorted(pack.workflow_ids),
            "terminology_keys": sorted(pack.terminology_keys),
            "capabilities": capabilities,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


_REGISTRY = CapabilityRegistry(
    capabilities=RECRUITMENT_CAPABILITIES,
    packs=(RECRUITMENT_PACK,),
)


def get_capability_registry() -> CapabilityRegistry:
    return _REGISTRY
