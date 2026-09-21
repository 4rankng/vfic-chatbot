"""Global domain-error → HTTP exception handlers.

Registers a handler for :class:`DomainError` (and its subclasses) so service
and API code can raise a framework-free domain error and still receive the
correct HTTP status with the ``{"detail": "<payload>"}`` shape, eliminating
per-route try/except boilerplate.

Starlette resolves handlers by walking the raised exception's MRO, so the
single base-class registration covers every subclass — including any added
later, which cannot be silently forgotten.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.shared.domain.errors import DomainError, InstallationError


def register_domain_exception_handlers(app: FastAPI) -> None:
    """Register domain-error handlers on *app*.

    Must be called once, after ``FastAPI()`` is created but before the
    app is mounted behind Socket.IO.
    """
    app.add_exception_handler(DomainError, _domain_handler)
    app.add_exception_handler(InstallationError, _installation_handler)
    app.add_exception_handler(RequestValidationError, _request_validation_handler)


async def _domain_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


async def _installation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, InstallationError)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": str(exc),
            "code": exc.code,
            "lifecycle": exc.lifecycle,
            "issues": exc.issues,
        },
    )


async def _request_validation_handler(request: Request, exc: Exception):
    assert isinstance(exc, RequestValidationError)
    if not request.url.path.startswith("/api/v1/admin/installation"):
        return await request_validation_exception_handler(request, exc)
    issues = [
        {
            "code": str(error["type"]).upper(),
            "message": str(error["msg"]),
            "path": ".".join(str(item) for item in error["loc"] if item != "body") or None,
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Installation request validation failed",
            "code": "INSTALLATION_VALIDATION_FAILED",
            "lifecycle": "UNKNOWN",
            "issues": issues,
        },
    )
