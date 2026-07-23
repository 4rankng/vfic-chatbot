"""Transport contracts for installation setup and public bootstrap."""

from __future__ import annotations

import json
from unittest.mock import Mock

from app.api import installation
from app.api.dependencies import require_admin
from app.core.errors import _installation_handler, _request_validation_handler
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from app.schemas.installation import InstallationRuntimeOut
from app.shared.domain.errors import InstallationError


def _route(path: str):
    return next(route for route in installation.router.routes if route.path == path)


def test_public_runtime_route_is_the_only_installation_route_without_admin_rbac() -> None:
    public = _route("/installation/runtime")
    assert all(dependency.call is not require_admin for dependency in public.dependant.dependencies)

    admin_routes = [
        route
        for route in installation.router.routes
        if route.path.startswith("/admin/installation")
    ]
    assert len(admin_routes) == 7
    for route in admin_routes:
        assert any(dependency.call is require_admin for dependency in route.dependant.dependencies)


async def test_public_runtime_endpoint_returns_only_the_safe_projection(monkeypatch) -> None:
    expected = InstallationRuntimeOut(
        lifecycle="ACTIVE",
        authority_generation=3,
        revision_id=None,
        pack_key="recruitment",
        pack_version="1",
        pack_contract_hash="a" * 64,
        manifest_checksum="b" * 64,
        customer_identity={"display_name": "Configured customer"},
        branding={"app_name": "Configured app"},
        locale="vi-VN",
        timezone="Asia/Ho_Chi_Minh",
        currency="VND",
        terminology={"lead": "Ứng viên"},
        capability_ids=["conversation"],
        readiness_code="READY",
        legacy_workspace=False,
    )

    async def runtime_view(_self):
        return expected

    monkeypatch.setattr(installation.InstallationService, "runtime_view", runtime_view)
    transport = Mock()
    transport.headers = {}
    response = await installation.get_installation_runtime(response=transport, db=object())

    assert response == expected
    assert "provider_policy" not in response.model_dump()
    assert "body_md" not in response.model_dump()
    assert transport.headers["Cache-Control"] == "no-store"


async def test_installation_error_handler_preserves_detail_and_stable_machine_fields() -> None:
    error = InstallationError(
        "Validation failed",
        code="INSTALLATION_VALIDATION_FAILED",
        lifecycle="DRAFT",
        status_code=422,
        issues=[{"code": "PACK_UNKNOWN", "message": "Unknown pack", "path": "pack_key"}],
    )

    response = await _installation_handler(None, error)
    payload = json.loads(response.body)

    assert response.status_code == 422
    assert payload == {
        "detail": "Validation failed",
        "code": "INSTALLATION_VALIDATION_FAILED",
        "lifecycle": "DRAFT",
        "issues": [{"code": "PACK_UNKNOWN", "message": "Unknown pack", "path": "pack_key"}],
    }


async def test_installation_request_validation_uses_the_stable_error_envelope() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/admin/installation/revisions",
            "headers": [],
            "query_string": b"",
        }
    )
    error = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "pack_key"),
                "msg": "Field required",
                "input": {},
            }
        ]
    )

    response = await _request_validation_handler(request, error)
    payload = json.loads(response.body)

    assert response.status_code == 422
    assert payload["code"] == "INSTALLATION_VALIDATION_FAILED"
    assert payload["lifecycle"] == "UNKNOWN"
    assert payload["issues"][0]["path"] == "pack_key"
