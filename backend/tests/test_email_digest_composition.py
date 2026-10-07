"""The composition root is the one seam both digest transports build through.

The worker and the console preview route must both reach the summarizer without
either growing an architecture backedge (``api -> app.graph`` would be a new
boundary exception, and services may not import the graph package at all).
"""

# pyright: reportArgumentType=false

from app.composition import email_digest as composition_module
from app.services.email_digest import service as digest_module
from app.workers import email_digest_worker as worker_module


async def test_composition_root_delegates_to_the_graph_factory(monkeypatch):
    """The concrete provider chain stays owned by app.graph.factories."""
    from app.graph import factories

    sentinel = object()
    captured: dict = {}

    async def fake_build(db):
        captured["db"] = db
        return sentinel

    monkeypatch.setattr(factories, "build_digest_summarizer", fake_build)

    db = object()
    assert await composition_module.build_digest_summarizer_for(db) is sentinel
    assert captured["db"] is db


async def test_worker_builds_its_summarizer_through_the_composition_root(monkeypatch):
    """The worker no longer imports app.graph directly."""
    import app.workers._db as db_module

    built: dict = {}

    async def fake_build(db):
        built["db"] = db
        return "summarizer"

    captured: dict = {}

    class _Session:
        async def __aenter__(self):
            built["session"] = True
            return "db-session"

        async def __aexit__(self, *_exc):
            return False

    async def fake_run_digest(db, *, summarizer=None):
        captured["db"] = db
        captured["summarizer"] = summarizer
        return _Result("sent", candidate_count=1)

    monkeypatch.setattr(composition_module, "build_digest_summarizer_for", fake_build)
    monkeypatch.setattr(db_module, "worker_session", lambda: _Session())
    monkeypatch.setattr(
        "app.services.email_digest.service.run_digest", fake_run_digest, raising=True
    )

    result = await worker_module._tick_async()
    assert result.status == "sent"
    assert captured["summarizer"] == "summarizer"
    assert built["db"] == "db-session"


class _Result:
    def __init__(self, status: str, candidate_count: int = 0) -> None:
        self.status = status
        self.candidate_count = candidate_count


async def test_preview_route_degrades_when_the_summarizer_cannot_build(monkeypatch):
    """An operator pressing "Gửi email thử" gets a sheet, not a 500.

    The scheduled tick instead fails loudly: a cron send must never quietly ship
    an unsummarised sheet, but a preview has no state to advance and is an
    explicit human action.
    """
    from app.api import integrations as api_module

    async def exploding_build(_db):
        raise RuntimeError("all providers failed")

    sent: dict = {}

    async def fake_send_test_digest(db, *, to_email, summarizer=None):
        sent["to_email"] = to_email
        sent["summarizer"] = summarizer
        return _Result("sent")

    monkeypatch.setattr(
        api_module, "build_digest_summarizer_for", exploding_build, raising=True
    )
    monkeypatch.setattr(api_module, "send_test_digest", fake_send_test_digest)

    result = await api_module.test_email_digest(
        _Body("xem.truoc@congty.vn"), _Result("admin"), _Result("db")
    )
    assert result.status == "sent"
    assert sent["to_email"] == "xem.truoc@congty.vn"
    assert sent["summarizer"] is None


async def test_preview_route_passes_the_built_summarizer_through(monkeypatch):
    from app.api import integrations as api_module

    sentinel = "summarizer"

    async def fake_build(_db):
        return sentinel

    sent: dict = {}

    async def fake_send_test_digest(db, *, to_email, summarizer=None):
        sent["summarizer"] = summarizer
        return _Result("sent")

    monkeypatch.setattr(api_module, "build_digest_summarizer_for", fake_build, raising=True)
    monkeypatch.setattr(api_module, "send_test_digest", fake_send_test_digest)

    await api_module.test_email_digest(
        _Body("xem.truoc@congty.vn"), _Result("admin"), _Result("db")
    )
    assert sent["summarizer"] == sentinel


class _Body:
    def __init__(self, to_email: str) -> None:
        self.to_email = to_email


def test_digest_module_still_exposes_the_public_digest_entry_points():
    assert callable(digest_module.run_digest)
    assert callable(digest_module.send_test_digest)
