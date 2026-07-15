"""Safety checks for the test-only Playwright database controller."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests import e2e_harness


def test_e2e_harness_refuses_non_test_database_names(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "VFIC_E2E_DATABASE_URL", "postgresql+asyncpg://user:pass@127.0.0.1/vfic"
    )
    monkeypatch.setenv(
        "VFIC_E2E_DATABASE_URL_SYNC", "postgresql+psycopg://user:pass@127.0.0.1/vfic"
    )

    with pytest.raises(RuntimeError, match="ending in `_e2e`"):
        e2e_harness._urls()


def test_e2e_harness_uses_documented_non_production_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VFIC_E2E_DATABASE_URL", raising=False)
    monkeypatch.delenv("VFIC_E2E_DATABASE_URL_SYNC", raising=False)

    async_url, sync_url = e2e_harness._urls()

    assert async_url.database == "vfic_e2e"
    assert sync_url.database == "vfic_e2e"
    assert e2e_harness.DEFAULT_ADMIN_EMAIL == "admin@example.org"


def test_e2e_harness_refuses_remote_database_even_with_test_suffix(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(
        "VFIC_E2E_DATABASE_URL",
        "postgresql+asyncpg://user:pass@db.example/vfic_e2e",
    )
    monkeypatch.setenv(
        "VFIC_E2E_DATABASE_URL_SYNC",
        "postgresql+psycopg://user:pass@db.example/vfic_e2e",
    )

    with pytest.raises(RuntimeError, match="loopback-only"):
        e2e_harness._urls()


def test_e2e_harness_refuses_mismatched_async_and_sync_endpoints(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(
        "VFIC_E2E_DATABASE_URL",
        "postgresql+asyncpg://user:pass@127.0.0.1:5432/vfic_e2e",
    )
    monkeypatch.setenv(
        "VFIC_E2E_DATABASE_URL_SYNC",
        "postgresql+psycopg://other:pass@127.0.0.1:5432/vfic_e2e",
    )

    with pytest.raises(RuntimeError, match="exact same endpoint"):
        e2e_harness._urls()


def test_integration_harness_refuses_remote_or_mismatched_database_urls():
    from sqlalchemy.engine import make_url

    from tests.integration.conftest import assert_local_matching_database_urls

    with pytest.raises(RuntimeError, match="loopback-only"):
        assert_local_matching_database_urls(
            make_url("postgresql+asyncpg://user:pass@db.example/vfic"),
            make_url("postgresql+psycopg://user:pass@db.example/vfic"),
        )
    with pytest.raises(RuntimeError, match="exact same endpoint"):
        assert_local_matching_database_urls(
            make_url("postgresql+asyncpg://user:pass@127.0.0.1:5432/vfic"),
            make_url("postgresql+psycopg://other:pass@127.0.0.1:5432/vfic"),
        )


def test_e2e_harness_refuses_remote_or_shared_redis(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VFIC_E2E_REDIS_URL", "redis://cache.example:6379/15")
    with pytest.raises(RuntimeError, match="loopback-only"):
        e2e_harness._redis_url()

    monkeypatch.setenv("VFIC_E2E_REDIS_URL", "redis://127.0.0.1:6382/0")
    with pytest.raises(RuntimeError, match="dedicated database 15"):
        e2e_harness._redis_url()


def test_e2e_backend_process_guard_rejects_external_sockets():
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(e2e_harness.NETWORK_GUARD_DIR), str(e2e_harness.BACKEND_DIR))
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import socket; socket.socket().connect(('203.0.113.1', 443))",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode != 0
    assert "external network is disabled in E2E" in result.stderr


def test_e2e_application_environment_scrubs_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    for key in (
        "ZALO_BOT_TOKEN",
        "ZALO_OA_ACCESS_TOKEN",
        "MINIMAX_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "RESEND_API_KEY",
    ):
        monkeypatch.setenv(key, "must-not-leak")

    environment = e2e_harness._application_environment()

    assert all(environment[key] == "" for key in (
        "ZALO_BOT_TOKEN",
        "ZALO_OA_ACCESS_TOKEN",
        "MINIMAX_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "RESEND_API_KEY",
    ))
    assert str(e2e_harness.NETWORK_GUARD_DIR) in environment["PYTHONPATH"]
