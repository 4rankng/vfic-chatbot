"""Pure project ownership and activation-readiness policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectActivationFacts:
    knowledge_mode: str | None
    has_discovery_card: bool = False
    has_direct_file: bool = False


def project_activation_error(facts: ProjectActivationFacts) -> str | None:
    """Return the frozen compatibility error, or ``None`` when activation is ready."""
    if facts.knowledge_mode == "DIRECT_CONTEXT":
        if not facts.has_discovery_card:
            return "Single-page Project needs a discovery card before activation"
        if not facts.has_direct_file:
            return "Single-page Project needs its page before activation"
        return None
    if facts.knowledge_mode == "RAG":
        return None
    return "Project has no owned knowledge base"


__all__ = ["ProjectActivationFacts", "project_activation_error"]
