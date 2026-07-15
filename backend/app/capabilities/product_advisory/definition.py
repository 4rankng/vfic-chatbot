"""Code-reviewed product-advisory pack with no commerce operational authority."""

from app.capabilities.contracts import CapabilityDefinition, IndustryPackDefinition
from app.capabilities.product_advisory.adapter import DESCRIPTOR

CAPABILITIES = (CapabilityDefinition("product_advisory", ("knowledge",), adapter_descriptor=DESCRIPTOR),)

PACK = IndustryPackDefinition(
    key="product_advisory",
    version="1",
    capability_ids=("conversation", "knowledge", *(item.capability_id for item in CAPABILITIES)),
    kernel_abi="1",
    compatible_operational_data=("product_advisory",),
    terminology_keys=("conversation", "offering", "organization"),
    runtime_ready=False,
)
