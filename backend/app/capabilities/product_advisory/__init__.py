"""Product-advisory capability boundary with no eager infrastructure imports."""

from app.capabilities.product_advisory.adapter import DESCRIPTOR, ProductAdvisoryAdapterDescriptor

__all__ = ["DESCRIPTOR", "ProductAdvisoryAdapterDescriptor"]
