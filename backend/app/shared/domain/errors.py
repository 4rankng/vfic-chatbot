"""Framework-free domain errors mapped by transport adapters at the edge."""


class NotFoundError(Exception):
    def __init__(self, message: str = "Not found") -> None:
        self.message = message
        super().__init__(message)


class ConflictError(Exception):
    def __init__(self, message: str = "Conflict") -> None:
        self.message = message
        super().__init__(message)


class ForbiddenError(Exception):
    def __init__(self, message: str = "Forbidden") -> None:
        self.message = message
        super().__init__(message)


class UpstreamError(Exception):
    def __init__(self, message: str = "Upstream service error") -> None:
        self.message = message
        super().__init__(message)


class DeliveryEligibilityError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InstallationError(Exception):
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


__all__ = [
    "ConflictError",
    "DeliveryEligibilityError",
    "ForbiddenError",
    "InstallationError",
    "NotFoundError",
    "UpstreamError",
]
