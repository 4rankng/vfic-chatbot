"""Tests for ProfileEnrichmentService — best-effort OA avatar/name persistence.

Covers: short-circuit when avatar+name already present, successful apply,
transport-error tolerance, missing-profile no-op, and non-overwrite of an
existing name.
"""
from __future__ import annotations


import pytest

from app.services.profile_enrichment import ProfileEnrichmentService
from app.services.zalo_oa_service import OAUserProfile

pytestmark = pytest.mark.asyncio


class _FakeRepo:
    """Minimal LeadRepository fake — only by_zalo_id is exercised."""

    def __init__(self, lead_row: dict | None) -> None:
        self._lead_row = lead_row

    async def by_zalo_id(self, zalo_id: str) -> dict | None:
        return self._lead_row


class _FakeDB:
    """Captures execute() calls + commit() for assertion."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []
        self.committed = False

    async def execute(self, sql, params: dict | None = None):
        self.executed.append((str(sql), params or {}))
        return None

    async def commit(self) -> None:
        self.committed = True

    async def get(self, _model, _lead_id):
        # The realtime emit path reloads the Lead row. Return None so the
        # `if saved is not None` guard skips the LeadEventBus call — realtime
        # propagation is tested elsewhere; here we focus on persistence.
        return None


class _FakeSender:
    """Returns a canned OAUserProfile (or raises) to simulate Zalo."""

    def __init__(self, profile: OAUserProfile | None, *, raises: bool = False) -> None:
        self._profile = profile
        self._raises = raises
        self.called_with: str | None = None

    async def get_user_detail(self, user_id: str) -> OAUserProfile | None:
        self.called_with = user_id
        if self._raises:
            raise ConnectionError("network down")
        return self._profile


def _make_service(
    db: _FakeDB,
    sender: _FakeSender,
    lead_row: dict | None,
) -> ProfileEnrichmentService:
    svc = ProfileEnrichmentService.__new__(ProfileEnrichmentService)
    svc.db = db  # type: ignore[assignment]
    svc.sender = sender  # type: ignore[assignment]
    svc._leads = _FakeRepo(lead_row)  # type: ignore[assignment]
    return svc


async def test_short_circuits_when_avatar_and_name_already_present() -> None:
    """No Zalo call when the lead already has both avatar and name."""
    db = _FakeDB()
    sender = _FakeSender(OAUserProfile(avatar_url="x", display_name="y"))
    svc = _make_service(
        db,
        sender,
        lead_row={"avatar_url": "https://existing.jpg", "name": "Existing"},
    )

    result = await svc.enrich_oa_user("oa:u1", user_id="u1")

    assert result is False
    assert sender.called_with is None
    assert db.executed == []
    assert db.committed is False


async def test_applies_avatar_and_name_for_missing_lead_profile() -> None:
    db = _FakeDB()
    profile = OAUserProfile(
        avatar_url="https://zalo.me/a.jpg", display_name="Nguyễn An"
    )
    sender = _FakeSender(profile)
    svc = _make_service(db, sender, lead_row={"avatar_url": None, "name": ""})

    result = await svc.enrich_oa_user("oa:u1", user_id="u1")

    assert result is True
    assert sender.called_with == "u1"
    assert len(db.executed) == 1
    sql_text, params = db.executed[0]
    assert "UPDATE leads" in sql_text
    assert params["zalo_id"] == "oa:u1"
    assert params["avatar_url"] == "https://zalo.me/a.jpg"
    assert params["display_name"] == "Nguyễn An"
    assert db.committed is True


async def test_returns_false_when_lead_does_not_exist() -> None:
    """No Zalo call + no DB write when there's no lead row yet."""
    db = _FakeDB()
    sender = _FakeSender(OAUserProfile(avatar_url="x", display_name="y"))
    svc = _make_service(db, sender, lead_row=None)

    result = await svc.enrich_oa_user("oa:missing", user_id="missing")

    assert result is False
    assert sender.called_with is None
    assert db.executed == []


async def test_transport_error_is_swallowed_and_returns_false() -> None:
    db = _FakeDB()
    sender = _FakeSender(None, raises=True)
    svc = _make_service(db, sender, lead_row={"avatar_url": None, "name": ""})

    result = await svc.enrich_oa_user("oa:u1", user_id="u1")

    assert result is False
    assert sender.called_with == "u1"
    assert db.executed == []
    assert db.committed is False


async def test_returns_false_when_profile_has_no_avatar_or_name() -> None:
    """Zalo returned an empty profile — nothing to persist."""
    db = _FakeDB()
    sender = _FakeSender(OAUserProfile(avatar_url="", display_name=""))
    svc = _make_service(db, sender, lead_row={"avatar_url": None, "name": ""})

    result = await svc.enrich_oa_user("oa:u1", user_id="u1")

    assert result is False
    assert db.executed == []
    assert db.committed is False


async def test_applies_avatar_only_when_display_name_empty() -> None:
    """An avatar without a name still enriches the avatar field."""
    db = _FakeDB()
    profile = OAUserProfile(avatar_url="https://zalo.me/a.jpg", display_name="")
    sender = _FakeSender(profile)
    svc = _make_service(db, sender, lead_row={"avatar_url": None, "name": ""})

    result = await svc.enrich_oa_user("oa:u1", user_id="u1")

    assert result is True
    sql_text, params = db.executed[0]
    assert params["avatar_url"] == "https://zalo.me/a.jpg"
    assert params["display_name"] == ""
