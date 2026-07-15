"""Static descriptor for the document-grounded product-advisory capability."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductAdvisoryAdapterDescriptor:
    capability_id: str = "product_advisory"
    supported_authority: tuple[str, ...] = ("document_facts", "knowledge_retrieval")
    unsupported_live_authority: tuple[str, ...] = ("stock", "order", "payment", "shipment")


DESCRIPTOR = ProductAdvisoryAdapterDescriptor()
