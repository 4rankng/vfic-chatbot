"""Closed-world registry of code-reviewed industry packs and capabilities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from app.capabilities.contracts import CapabilityDefinition, IndustryPackDefinition, ResolvedPack
from app.capabilities.recruitment.definition import CAPABILITIES as RECRUITMENT_CAPABILITIES
from app.capabilities.recruitment.definition import PACK as RECRUITMENT_PACK

SUPPORTED_KERNEL_ABI = "1"
PACK_CONTRACT_SCHEMA_VERSION = 1


class CapabilityRegistry:
    def __init__(
        self,
        *,
        capabilities: Iterable[CapabilityDefinition],
        packs: Iterable[IndustryPackDefinition],
    ) -> None:
        self._capabilities = self._unique_by_id(capabilities, "capability_id")
        self._packs = self._unique_by_id(packs, "key")
        self._validate_dependency_graph()
        for pack in self._packs.values():
            self.validate_selection(pack.key, pack.capability_ids)
            self._validate_owners(pack)

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
        return tuple(self._capabilities[key] for key in sorted(self._capabilities))  # type: ignore[return-value]

    def validate_selection(self, pack_key: str, capability_ids: Iterable[str]) -> tuple[str, ...]:
        pack = self.get_pack(pack_key)
        provided = tuple(capability_ids)
        if len(provided) != len(set(provided)):
            raise ValueError("duplicate capability IDs are forbidden")
        selected = tuple(sorted(provided))
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

    def resolve(
        self,
        pack_key: str,
        pack_version: str,
        capability_ids: Iterable[str],
        pack_contract_hash: str,
        *,
        kernel_abi: str = SUPPORTED_KERNEL_ABI,
        schema_version: int = PACK_CONTRACT_SCHEMA_VERSION,
    ) -> ResolvedPack:
        pack = self.get_pack(pack_key)
        if schema_version != PACK_CONTRACT_SCHEMA_VERSION:
            raise ValueError(f"unsupported pack contract schema: {schema_version}")
        if kernel_abi != SUPPORTED_KERNEL_ABI or pack.kernel_abi != kernel_abi:
            raise ValueError(f"unsupported kernel ABI: {kernel_abi}")
        if pack.version != pack_version:
            raise ValueError(f"unsupported pack version: {pack_version}")
        selected = self.validate_selection(pack_key, capability_ids)
        expected_hash = self.pack_contract_hash(pack_key)
        if pack_contract_hash != expected_hash:
            raise ValueError("pack contract hash mismatch")
        return ResolvedPack(
            pack=pack,
            capabilities=tuple(self._capabilities[item] for item in selected),
            contract_hash=expected_hash,
            adapter_descriptors=tuple(
                descriptor
                for item in selected
                if (descriptor := self._capabilities[item].adapter_descriptor) is not None
            ),
        )

    def export_pack_contract(self, pack_key: str) -> dict:
        pack = self.get_pack(pack_key)
        return {
            "schema_version": PACK_CONTRACT_SCHEMA_VERSION,
            "pack": self._pack_payload(pack),
            "contract_hash": self.pack_contract_hash(pack_key),
        }

    def pack_contract_hash(self, pack_key: str) -> str:
        """Hash only the selected pack contract, not unrelated registry entries."""
        pack = self.get_pack(pack_key)
        envelope = {
            "schema_version": PACK_CONTRACT_SCHEMA_VERSION,
            "pack": self._pack_payload(pack),
        }
        encoded = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _pack_payload(self, pack: IndustryPackDefinition) -> dict:
        capabilities = []
        for capability_id in sorted(pack.capability_ids):
            capability = self._capabilities[capability_id]
            capabilities.append(
                {
                    "id": capability.capability_id,  # type: ignore[attr-defined]
                    "dependencies": sorted(capability.dependencies),  # type: ignore[attr-defined]
                    "authority_class": capability.authority_class,  # type: ignore[attr-defined]
                    "api_routes": sorted(capability.api_routes),  # type: ignore[attr-defined]
                    "frontend_resources": sorted(capability.frontend_resources),  # type: ignore[attr-defined]
                    "dashboard_owner": capability.dashboard_owner,  # type: ignore[attr-defined]
                    "conversation_slots": sorted(capability.conversation_slots),  # type: ignore[attr-defined]
                }
            )
        return {
            "key": pack.key,
            "version": pack.version,
            "kernel_abi": pack.kernel_abi,
            "compatible_operational_data": sorted(pack.compatible_operational_data),
            "workflow_ids": sorted(pack.workflow_ids),
            "terminology_keys": sorted(pack.terminology_keys),
            "capabilities": capabilities,
        }

    def _validate_dependency_graph(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(capability_id: str) -> None:
            if capability_id in visiting:
                raise ValueError(f"capability dependency cycle: {capability_id}")
            if capability_id in visited:
                return
            capability = self._capabilities.get(capability_id)
            if capability is None:
                raise ValueError(f"unknown capability: {capability_id}")
            visiting.add(capability_id)
            for dependency in capability.dependencies:  # type: ignore[attr-defined]
                visit(dependency)
            visiting.remove(capability_id)
            visited.add(capability_id)

        for capability_id in self._capabilities:
            visit(capability_id)

    def _validate_owners(self, pack: IndustryPackDefinition) -> None:
        routes: set[str] = set()
        resources: set[str] = set()
        slots: set[str] = set()
        dashboards = 0
        for capability_id in pack.capability_ids:
            capability = self._capabilities[capability_id]
            for values, seen, label in (
                (capability.api_routes, routes, "route"),
                (capability.frontend_resources, resources, "resource"),
                (capability.conversation_slots, slots, "conversation slot"),
            ):
                if len(values) != len(set(values)):
                    raise ValueError(f"duplicate {label} in capability {capability_id}")
                duplicate = seen.intersection(values)
                if duplicate:
                    raise ValueError(f"duplicate {label} owner: {sorted(duplicate)}")
                seen.update(values)
            dashboards += int(capability.dashboard_owner)
            descriptor = capability.adapter_descriptor
            if descriptor is not None and descriptor.capability_id != capability_id:
                raise ValueError(
                    f"adapter descriptor ownership mismatch: {descriptor.capability_id}"
                )
        if dashboards > 1:
            raise ValueError("multiple dashboard owners")


_REGISTRY = CapabilityRegistry(
    capabilities=RECRUITMENT_CAPABILITIES,
    packs=(RECRUITMENT_PACK,),
)


def get_capability_registry() -> CapabilityRegistry:
    return _REGISTRY
