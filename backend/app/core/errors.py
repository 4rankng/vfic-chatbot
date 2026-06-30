"""Global domain-error → HTTP exception handlers.

Registers handlers for the four service-layer domain errors so they
automatically return the correct HTTP status code with the
``{"detail": "<message>"}`` shape, eliminating per-route try/except
boilerplate.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UpstreamError,
)

_STATUS_MAP: dict[type[Exception], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    ForbiddenError: 403,
    UpstreamError: 502,
}


def register_domain_exception_handlers(app: FastAPI) -> None:
    """Register domain-error handlers on *app*.

    Must be called once, after ``FastAPI()`` is created but before the
    app is mounted behind Socket.IO.
    """
    for exc_class, status_code in _STATUS_MAP.items():
        app.add_exception_handler(exc_class, _make_handler(status_code))


def _make_handler(status_code: int):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"detail": str(exc)},
        )

    return handler
