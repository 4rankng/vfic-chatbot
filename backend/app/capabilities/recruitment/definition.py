"""Code-reviewed recruitment pack definition without runtime side effects."""

from app.capabilities.contracts import CapabilityDefinition, IndustryPackDefinition

CAPABILITIES = (
    CapabilityDefinition("conversation"),
    CapabilityDefinition("knowledge", ("conversation",)),
    CapabilityDefinition("candidate_intake", ("conversation",)),
    CapabilityDefinition("job_advisory", ("candidate_intake", "knowledge")),
    CapabilityDefinition("channel.zalo", ("conversation",)),
)

PACK = IndustryPackDefinition(
    key="recruitment",
    version="1",
    capability_ids=tuple(capability.capability_id for capability in CAPABILITIES),
    kernel_abi="1",
    compatible_operational_data=("recruitment",),
    runtime_ready=False,
)
