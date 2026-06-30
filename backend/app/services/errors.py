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
