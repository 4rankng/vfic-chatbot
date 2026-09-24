"""Tests for the allowed_hosts setting (TrustedHostMiddleware allowlist).

SEC-06 wires ``TrustedHostMiddleware(allowed_hosts=settings.allowed_hosts_list)``.
The default must keep production, the compose healthchecks, and local dev
working, and a ``*`` value must fail at boot: Starlette treats ``*`` as "allow
any Host", which silently turns the host allowlist into a no-op.
"""

from __future__ import annotations

import pytest


def _make_settings(monkeypatch, allowed_hosts: str | None):
    """Construct Settings with ALLOWED_HOSTS overridden (or cleared) via env."""
    from app.core.config import Settings

    if allowed_hosts is None:
        monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    else:
        monkeypatch.setenv("ALLOWED_HOSTS", allowed_hosts)
    return Settings()


def test_default_allowed_hosts_cover_prod_healthchecks_and_local_dev(monkeypatch):
    settings = _make_settings(monkeypatch, None)

    assert settings.allowed_hosts_list == ["bot.tingting.vip", "localhost", "127.0.0.1"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", ["example.com"]),
        (" example.com , api.example.com ", ["example.com", "api.example.com"]),
        ("example.com,,", ["example.com"]),
    ],
)
def test_allowed_hosts_list_strips_blanks_and_whitespace(monkeypatch, raw, expected):
    assert _make_settings(monkeypatch, raw).allowed_hosts_list == expected


def test_wildcard_allowed_hosts_refuses_to_boot(monkeypatch):
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS must not contain"):
        _make_settings(monkeypatch, "bot.tingting.vip,*")
