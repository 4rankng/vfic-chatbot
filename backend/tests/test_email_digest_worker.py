"""Email digest worker tick: quiet statuses stay quiet, sends log info."""

# pyright: reportArgumentType=false

import logging

from app.workers import email_digest_worker as worker_module


class _Result:
    def __init__(self, status: str, candidate_count: int = 0) -> None:
        self.status = status
        self.candidate_count = candidate_count


def test_tick_quiet_statuses(monkeypatch):
    async def fake_tick():
        return _Result("not_due")

    monkeypatch.setattr(worker_module, "_tick_async", fake_tick)
    assert worker_module.run_email_digest_tick() == "not_due"


def test_tick_sent_logs_info(monkeypatch, caplog):
    async def fake_tick():
        return _Result("sent", candidate_count=3)

    monkeypatch.setattr(worker_module, "_tick_async", fake_tick)
    with caplog.at_level(logging.INFO, logger="app.workers.email_digest_worker"):
        status = worker_module.run_email_digest_tick()
    assert status == "sent"
    assert any("candidates=3" in record.message for record in caplog.records)


def test_tick_unconfigured_logs_warning(monkeypatch, caplog):
    async def fake_tick():
        return _Result("unconfigured")

    monkeypatch.setattr(worker_module, "_tick_async", fake_tick)
    with caplog.at_level(logging.WARNING, logger="app.workers.email_digest_worker"):
        status = worker_module.run_email_digest_tick()
    assert status == "unconfigured"
    assert any(record.levelno == logging.WARNING for record in caplog.records)
