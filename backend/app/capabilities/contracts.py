"""Non-executable contracts for code-owned industry capabilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    """One auditable kernel capability and its dependency closure."""

    capability_id: str
    dependencies: tuple[str, ...] = ()
    authority_class: str = "capability"
    api_routes: tuple[str, ...] = ()
    frontend_resources: tuple[str, ...] = ()
    dashboard_owner: bool = False
    conversation_slots: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IndustryPackDefinition:
    """A code-reviewed set of capabilities, never an executable plug-in."""

    key: str
    version: str
    capability_ids: tuple[str, ...]
    kernel_abi: str
    compatible_operational_data: tuple[str, ...] = ()
    workflow_ids: tuple[str, ...] = ()
    terminology_keys: tuple[str, ...] = ()
    runtime_ready: bool = False
