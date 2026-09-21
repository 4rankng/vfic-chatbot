"""Framework-free domain errors mapped by transport adapters at the edge."""

from __future__ import annotations

from typing import Any

__all__ = [
    "BadRequestError",
    "ConflictError",
    "DeliveryEligibilityError",
    "DomainError",
    "ForbiddenError",
    "GoneError",
    "InstallationError",
    "NotFoundError",
    "RateLimitedError",
    "UnauthorizedError",
    "UpstreamError",
    "ValidationError",
]


class DomainError(Exception):
    """Base class for every domain error.

    ``status_code`` is the transport status the edge maps the error to, and
    ``headers`` carries any response headers the status requires.

    ``detail`` is the exact JSON value serialised under the response's
    ``detail`` key. It is normally a message string; a client contract that
    needs structured detail (for example per-field validation issues) may
    supply a JSON-serialisable mapping instead.
    """

    status_code: int = 500
    headers: dict[str, str] | None = None

    def __init__(self, detail: Any) -> None:
        self.detail = detail
        self.message = detail if isinstance(detail, str) else "Request failed"
        super().__init__(self.message)


class NotFoundError(DomainError):
    status_code = 404

    def __init__(self, message: str = "Not found") -> None:
        super().__init__(message)


class ConflictError(DomainError):
    status_code = 409

    def __init__(self, message: str = "Conflict") -> None:
        super().__init__(message)


class ForbiddenError(DomainError):
    status_code = 403

    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message)


class UpstreamError(DomainError):
    status_code = 502

    def __init__(self, message: str = "Upstream service error") -> None:
        super().__init__(message)


class DeliveryEligibilityError(DomainError):
    """A message cannot be delivered inside the channel's eligibility window."""

    status_code = 422

    def __init__(self, detail: Any) -> None:
        super().__init__(detail)


class BadRequestError(DomainError):
    status_code = 400

    def __init__(self, detail: Any = "Bad request") -> None:
        super().__init__(detail)


class UnauthorizedError(DomainError):
    status_code = 401
    headers = {"WWW-Authenticate": "Bearer"}

    def __init__(self, detail: Any = "Unauthorized") -> None:
        super().__init__(detail)


class GoneError(DomainError):
    status_code = 410

    def __init__(self, detail: Any = "Gone") -> None:
        super().__init__(detail)


class ValidationError(DomainError):
    status_code = 422

    def __init__(self, detail: Any = "Unprocessable request") -> None:
        super().__init__(detail)


class RateLimitedError(DomainError):
    status_code = 429

    def __init__(self, detail: Any = "Too many requests") -> None:
        super().__init__(detail)


class InstallationError(DomainError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        lifecycle: str,
        status_code: int = 409,
        issues: list[dict[str, str | None]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.lifecycle = lifecycle
        self.status_code = status_code
        self.issues = issues or []
