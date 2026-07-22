"""Shared-kernel purity and compatibility contracts."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


SHARED_ROOT = Path(__file__).parents[1] / "app" / "shared"
FORBIDDEN_PREFIXES = (
    "fastapi",
    "httpx",
    "pydantic",
    "redis",
    "rq",
    "socketio",
    "sqlalchemy",
    "app.api",
    "app.channels",
    "app.core",
    "app.graph",
    "app.models",
    "app.services",
    "app.workers",
)


def test_shared_contracts_have_no_framework_or_infrastructure_imports() -> None:
    violations: list[str] = []
    for path in SHARED_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        modules = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        modules.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        violations.extend(
            f"{path.relative_to(SHARED_ROOT)} -> {module}"
            for module in modules
            if module.startswith(FORBIDDEN_PREFIXES)
        )
    assert not violations


def test_error_compatibility_imports_preserve_class_identity() -> None:
    from app.services import errors as legacy
    from app.shared.domain import errors as canonical

    assert legacy.NotFoundError is canonical.NotFoundError
    assert legacy.ConflictError is canonical.ConflictError
    assert legacy.InstallationError is canonical.InstallationError


def test_outbound_compatibility_imports_preserve_object_identity() -> None:
    from app.graph import outbound_telemetry as legacy
    from app.shared.application import outbound as canonical

    assert legacy.OutboundTelemetry is canonical.OutboundTelemetry
    assert legacy.combine_outbound_telemetry is canonical.combine_outbound_telemetry


def test_outbound_contract_is_immutable_and_contains_no_payload_fields() -> None:
    from app.shared.application.outbound import OutboundTelemetry

    telemetry = OutboundTelemetry(adapter="zalo_bot", provider_request_ms=10)
    with pytest.raises(FrozenInstanceError):
        telemetry.provider_request_ms = 11  # type: ignore[misc]
    assert not {"text", "recipient_id", "token", "payload"} & telemetry.__dict__.keys()


def test_classification_compatibility_matches_canonical_policy() -> None:
    from app.graph.send_classification import AMBIGUOUS_SEND_CLASSES as legacy_classes
    from app.shared.application.outbound import (
        AMBIGUOUS_SEND_CLASSES,
        is_ambiguous_send,
    )

    assert legacy_classes is AMBIGUOUS_SEND_CLASSES
    assert is_ambiguous_send("read_timeout", ok=False)
    assert not is_ambiguous_send("connect_error", ok=False)
    assert not is_ambiguous_send("read_timeout", ok=True)
