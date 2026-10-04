"""Code-reviewed recruitment pack definition without runtime side effects."""

from app.capabilities.contracts import CapabilityDefinition, IndustryPackDefinition

CAPABILITIES = (
    CapabilityDefinition(
        "conversation",
        api_routes=("/api/v1/conversations",),
        frontend_resources=("conversations",),
    ),
    CapabilityDefinition(
        "knowledge",
        ("conversation",),
        api_routes=("/api/v1/knowledge",),
        frontend_resources=("knowledge_sources", "projects"),
    ),
    CapabilityDefinition(
        "candidate_intake",
        ("conversation",),
        api_routes=("/api/v1/leads",),
        conversation_slots=("row", "filters", "context", "actions"),
    ),
    CapabilityDefinition(
        "job_advisory",
        ("candidate_intake", "knowledge"),
        api_routes=("/api/v1/jobs",),
        dashboard_owner=True,
    ),
    CapabilityDefinition(
        "channel.zalo",
        ("conversation",),
        authority_class="channel",
        frontend_resources=("settings",),
    ),
)

PACK = IndustryPackDefinition(
    key="recruitment",
    version="1",
    capability_ids=tuple(capability.capability_id for capability in CAPABILITIES),
    kernel_abi="1",
    compatible_operational_data=("recruitment",),
    workflow_ids=("candidate_intake",),
    terminology_keys=("application", "candidate", "conversation", "job", "lead", "organization"),
    runtime_ready=True,
)
