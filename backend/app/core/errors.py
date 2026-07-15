"""Global domain-error → HTTP exception handlers.

Registers handlers for the four service-layer domain errors so they
automatically return the correct HTTP status code with the
``{"detail": "<message>"}`` shape, eliminating per-route try/except
boilerplate.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.errors import (
    ConflictError,
    DeliveryEligibilityError,
    ForbiddenError,
    InstallationError,
    NotFoundError,
    UpstreamError,
)

_STATUS_MAP: dict[type[Exception], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    ForbiddenError: 403,
    UpstreamError: 502,
    DeliveryEligibilityError: 422,
}


def register_domain_exception_handlers(app: FastAPI) -> None:
    """Register domain-error handlers on *app*.

    Must be called once, after ``FastAPI()`` is created but before the
    app is mounted behind Socket.IO.
    """
    for exc_class, status_code in _STATUS_MAP.items():
        app.add_exception_handler(exc_class, _make_handler(status_code))
    app.add_exception_handler(InstallationError, _installation_handler)
    app.add_exception_handler(RequestValidationError, _request_validation_handler)


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


def _make_handler(status_code: int):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"detail": str(exc)},
        )

    return handler
