"""Non-executable contracts for code-owned industry capabilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    """One auditable kernel capability and its dependency closure."""

    capability_id: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IndustryPackDefinition:
    """A code-reviewed set of capabilities, never an executable plug-in."""

    key: str
    version: str
    capability_ids: tuple[str, ...]
    kernel_abi: str
    compatible_operational_data: tuple[str, ...] = ()
    runtime_ready: bool = False
