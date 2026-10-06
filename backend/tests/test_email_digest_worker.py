"""Email digest worker tick: quiet statuses stay quiet, sends log info."""

# pyright: reportArgumentType=false

import logging

import pytest

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


# ─── summarizer provider failover ───────────────────────────────────────────
#
# The summarizer used to bind a single provider, so a rate-limited or
# exhausted provider silently emptied every summary cell in the digest.


async def test_digest_summarizer_fails_over_to_the_next_provider(monkeypatch):
    """A dead primary provider must not empty the digest's summary column."""
    from types import SimpleNamespace

    from app.graph import factories

    class _Boom:
        async def ainvoke(self, _messages):
            raise RuntimeError("429 rate limited")

    class _Good:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content="Ứng viên hỏi về lương và ca làm.")

    monkeypatch.setattr(
        factories, "_chat_for_role", lambda *a, **k: _Boom(), raising=True
    )
    monkeypatch.setattr(
        factories,
        "_build_failover_chain",
        lambda **k: [_Good()],
        raising=True,
    )

    class _Settings:
        def __init__(self, _db):
            pass

        async def resolve_minimax(self):
            return SimpleNamespace(
                api_key="mm",
                enabled=True,
                default_provider="minimax",
                extractor_model="",
                agent_model="mm-agent",
            )

        async def resolve_openrouter(self):
            return SimpleNamespace(
                api_key="or",
                enabled=True,
                agent_model="or-agent",
                extractor_model="",
            )

        async def resolve_custom_llm(self):
            return SimpleNamespace(enabled=False, api_key=None)

        async def resolve_llm_failover_order(self):
            return ()

    import app.services.integration_settings as integration_settings

    monkeypatch.setattr(
        integration_settings, "IntegrationSettingsService", _Settings, raising=True
    )

    summarize = await factories.build_digest_summarizer(None)
    assert await summarize("sys", "user") == "Ứng viên hỏi về lương và ca làm."


async def test_digest_summarizer_raises_when_every_provider_fails(monkeypatch):
    """All providers down must surface as an error, not a silent empty string."""
    from types import SimpleNamespace

    from app.graph import factories

    class _Boom:
        async def ainvoke(self, _messages):
            raise RuntimeError("provider down")

    monkeypatch.setattr(
        factories, "_chat_for_role", lambda *a, **k: _Boom(), raising=True
    )
    monkeypatch.setattr(factories, "_build_failover_chain", lambda **k: [_Boom()], raising=True)

    class _Settings:
        def __init__(self, _db):
            pass

        async def resolve_minimax(self):
            return SimpleNamespace(
                api_key="mm", enabled=True, default_provider="minimax",
                extractor_model="", agent_model="mm-agent",
            )

        async def resolve_openrouter(self):
            return SimpleNamespace(api_key="or", enabled=True, agent_model="or", extractor_model="")

        async def resolve_custom_llm(self):
            return SimpleNamespace(enabled=False, api_key=None)

        async def resolve_llm_failover_order(self):
            return ()

    import app.services.integration_settings as integration_settings

    monkeypatch.setattr(
        integration_settings, "IntegrationSettingsService", _Settings, raising=True
    )

    summarize = await factories.build_digest_summarizer(None)
    with pytest.raises(RuntimeError, match="all 2 configured providers failed"):
        await summarize("sys", "user")
