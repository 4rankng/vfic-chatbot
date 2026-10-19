"""ODS insights worker tick: quiet statuses stay quiet, sends log info.

Mirrors ``test_email_digest_worker.py`` — the tick's async body is replaced,
so no DB, Redis, or network is touched.
"""

# pyright: reportArgumentType=false

import logging


from app.workers import ods_insights_worker as worker_module


class _Result:
    def __init__(self, status: str, insights_count: int = 0, missing=None) -> None:
        self.status = status
        self.insights_count = insights_count
        self.missing = missing or []
        self.error = None


def test_tick_quiet_statuses(monkeypatch):
    async def fake_tick():
        return _Result("disabled")

    monkeypatch.setattr(worker_module, "_tick_async", fake_tick)
    assert worker_module.run_ods_insights_tick() == "disabled"


def test_tick_sent_logs_info(monkeypatch, caplog):
    async def fake_tick():
        return _Result("sent", insights_count=7)

    monkeypatch.setattr(worker_module, "_tick_async", fake_tick)
    with caplog.at_level(logging.INFO, logger="app.workers.ods_insights_worker"):
        status = worker_module.run_ods_insights_tick()
    assert status == "sent"
    assert any("calls=7" in record.message for record in caplog.records)


def test_tick_unconfigured_logs_warning(monkeypatch, caplog):
    async def fake_tick():
        return _Result("unconfigured", missing=["api_key"])

    monkeypatch.setattr(worker_module, "_tick_async", fake_tick)
    with caplog.at_level(logging.WARNING, logger="app.workers.ods_insights_worker"):
        status = worker_module.run_ods_insights_tick()
    assert status == "unconfigured"
    assert any("api_key" in record.message for record in caplog.records)


async def test_tick_passes_the_shared_summarizer_into_the_run(monkeypatch):
    """The worker must build the digest summarizer and hand it to the service."""
    captured: dict = {}

    async def fake_summarizer_builder(_db):
        return "summarizer"

    async def fake_run(db, *, summarizer=None):
        captured["db"] = db
        captured["summarizer"] = summarizer

        class _R:
            status = "empty"
            insights_count = 0
            missing: list = []
            error = None

        return _R()

    class _FakeSession:
        async def __aenter__(self):
            return "db-session"

        async def __aexit__(self, *_exc):
            return False

    import app.composition.email_digest as composition
    import app.services.ods as ods_service
    import app.workers._db as workers_db

    monkeypatch.setattr(composition, "build_digest_summarizer_for", fake_summarizer_builder)
    monkeypatch.setattr(ods_service, "run_ods_insights", fake_run)
    monkeypatch.setattr(workers_db, "worker_session", lambda: _FakeSession())

    status_result = await worker_module._tick_async()
    assert status_result.status == "empty"
    assert captured["db"] == "db-session"
    assert captured["summarizer"] == "summarizer"


async def test_tick_survives_a_dead_summarizer_chain(monkeypatch):
    """All providers down must not kill the tick — the letter ships, empty."""
    captured: dict = {}

    async def dead_summarizer_builder(_db):
        raise RuntimeError("all providers failed")

    async def fake_run(db, *, summarizer=None):
        captured["summarizer"] = summarizer

        class _R:
            status = "sent"
            insights_count = 2
            missing: list = []
            error = None

        return _R()

    class _FakeSession:
        async def __aenter__(self):
            return "db-session"

        async def __aexit__(self, *_exc):
            return False

    import app.composition.email_digest as composition
    import app.services.ods as ods_service
    import app.workers._db as workers_db

    monkeypatch.setattr(composition, "build_digest_summarizer_for", dead_summarizer_builder)
    monkeypatch.setattr(ods_service, "run_ods_insights", fake_run)
    monkeypatch.setattr(workers_db, "worker_session", lambda: _FakeSession())

    status_result = await worker_module._tick_async()
    assert status_result.status == "sent"
    assert captured["summarizer"] is None


def test_cron_env_is_valid_and_daily_by_default():
    """ODS_INSIGHTS_CRON must parse as cron and default to 01:00 UTC daily."""
    from crontab import CronTab

    from app.core.config import get_settings

    settings = get_settings()
    assert settings.ods_insights_cron == "0 1 * * *"
    assert CronTab(settings.ods_insights_cron) is not None
