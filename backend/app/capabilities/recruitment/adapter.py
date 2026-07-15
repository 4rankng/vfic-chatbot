"""Delegation-only recruitment descriptor; runtime extraction belongs to Phase 6."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecruitmentAdapterDescriptor:
    capability_id: str = "candidate_intake"
    legacy_models: tuple[str, ...] = ("Lead", "Job")
    legacy_routes: tuple[str, ...] = ("/api/v1/leads", "/api/v1/jobs")


DESCRIPTOR = RecruitmentAdapterDescriptor()
