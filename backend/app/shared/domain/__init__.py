"""Framework-free domain primitives shared across bounded contexts."""

from app.shared.domain.errors import (
    ConflictError,
    DeliveryEligibilityError,
    ForbiddenError,
    InstallationError,
    NotFoundError,
    UpstreamError,
)

__all__ = [
    "ConflictError",
    "DeliveryEligibilityError",
    "ForbiddenError",
    "InstallationError",
    "NotFoundError",
    "UpstreamError",
]
