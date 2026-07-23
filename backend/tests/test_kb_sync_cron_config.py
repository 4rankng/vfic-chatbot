"""Tests for the kb_sync_cron setting (cron expression + fail-fast validation).

The cron string pins the daily KB-from-link re-ingest to a wall-clock time and
is validated at Settings instantiation so a malformed env value fails fast at
startup rather than silently mis-firing at the first scheduled tick.
"""

from __future__ import annotations

import pytest


def _make_settings(monkeypatch, kb_sync_cron: str | None):
    """Construct Settings with KB_SYNC_CRON overridden (or cleared) via env.

    pydantic-settings reads env vars on construction; monkeypatch.setenv/delenv
    auto-restores on test teardown (xdist- and exception-safe).
    """
    from app.core.config import Settings

    if kb_sync_cron is None:
        monkeypatch.delenv("KB_SYNC_CRON", raising=False)
    else:
        monkeypatch.setenv("KB_SYNC_CRON", kb_sync_cron)
    return Settings()


def test_default_kb_sync_cron_is_03_00_ict_in_utc(monkeypatch):
    s = _make_settings(monkeypatch, None)
    assert s.kb_sync_cron == "0 20 * * *"  # 03:00 ICT = 20:00 UTC


@pytest.mark.parametrize(
    "expr",
    [
        "0 20 * * *",     # default — 03:00 ICT
        "0 3 * * *",      # override to 03:00 UTC
        "*/15 * * * *",   # every 15 min
        "0 0 1 * *",      # monthly
        "30 2 * * 1-5",   # weekdays at 02:30
        "@daily",         # crontab macro — accepted by python-crontab + rq-scheduler
    ],
)
def test_accepts_valid_cron_expressions(monkeypatch, expr: str):
    s = _make_settings(monkeypatch, expr)
    assert s.kb_sync_cron == expr


@pytest.mark.parametrize(
    "expr",
    [
        "",               # empty
        "not a cron",     # garbage
        "99 99 * * *",    # out-of-range fields
        "0 24 * * *",     # hour out of range
    ],
)
def test_rejects_invalid_cron_expressions(monkeypatch, expr: str):
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        _make_settings(monkeypatch, expr)

    # The helpful message naming the field must reach the operator.
    assert "kb_sync_cron" in str(exc_info.value)
