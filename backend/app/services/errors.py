"""Domain-level exceptions for service layer.

Raised by services; caught by API routes and mapped to HTTP status codes.
No HTTP framework imports — these are pure domain errors.
"""


class NotFoundError(Exception):
    """Entity does not exist (→ 404)."""

    def __init__(self, message: str = "Not found") -> None:
        self.message = message
        super().__init__(message)


class ConflictError(Exception):
    """Duplicate / state conflict (→ 409)."""

    def __init__(self, message: str = "Conflict") -> None:
        self.message = message
        super().__init__(message)


class ForbiddenError(Exception):
    """Operation not allowed for this caller (→ 403)."""

    def __init__(self, message: str = "Forbidden") -> None:
        self.message = message
        super().__init__(message)


class UpstreamError(Exception):
    """External dependency failure (→ 502)."""

    def __init__(self, message: str = "Upstream service error") -> None:
        self.message = message
        super().__init__(message)


class DeliveryEligibilityError(Exception):
    """The channel cannot accept an outbound message yet (→ 422)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InstallationError(Exception):
    """Installation lifecycle/readiness failure with a stable machine code."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        lifecycle: str,
        status_code: int = 409,
        issues: list[dict[str, str | None]] | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.lifecycle = lifecycle
        self.status_code = status_code
        self.issues = issues or []
        super().__init__(message)
