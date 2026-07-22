"""Tests for OA contact-profile enrichment."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.profile_enrichment import (
    ProfileEnrichmentService,
    normalize_oa_profile_display_name,
)
from app.services.zalo_oa_service import OAUserProfile

pytestmark = pytest.mark.asyncio


class _FakeConversations:
    def __init__(self, contact) -> None:
        self._conversation = SimpleNamespace(contact=contact) if contact else None

    async def get_by_zalo(self, _zalo_id: str):
        return self._conversation


class _FakeDB:
    def __init__(self, saved_lead=None) -> None:
        self.saved_lead = saved_lead
        self.leads = [saved_lead] if saved_lead is not None else []
        self.committed = False

    async def scalars(self, _statement):
        return SimpleNamespace(all=lambda: self.leads)

    async def commit(self) -> None:
        self.committed = True


class _FakeSender:
    def __init__(self, profile: OAUserProfile | None, *, raises: bool = False) -> None:
        self._profile = profile
        self._raises = raises
        self.called_with: str | None = None
        self.call_count = 0

    async def get_user_detail(self, user_id: str) -> OAUserProfile | None:
        self.called_with = user_id
        self.call_count += 1
        if self._raises:
            raise ConnectionError("network down")
        return self._profile


@pytest.fixture(autouse=True)
def _profile_lookup_guard(monkeypatch):
    async def claim(_zalo_id: str, *, wait_for_inflight: bool):
        return True, "owner"

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.profile_enrichment._claim_profile_lookup", claim)
    monkeypatch.setattr("app.services.profile_enrichment._mark_profile_lookup_done", no_op)
    monkeypatch.setattr("app.services.profile_enrichment._release_profile_lookup", no_op)
    monkeypatch.setattr("app.services.profile_enrichment.LeadEventBus.lead_updated", no_op)


def _make_service(
    db: _FakeDB,
    sender: _FakeSender,
    lead_row: dict | None,
    contact,
) -> ProfileEnrichmentService:
    if contact is not None and not hasattr(contact, "id"):
        contact.id = "contact-id"
    service = ProfileEnrichmentService.__new__(ProfileEnrichmentService)
    service.db = db  # type: ignore[assignment]
    service.sender = sender  # type: ignore[assignment]
    service._conversations = _FakeConversations(contact)  # type: ignore[assignment]
    return service


async def test_short_circuits_when_contact_profile_is_complete() -> None:
    contact = SimpleNamespace(display_name="Bé Gấu", avatar_url="https://existing.jpg")
    db = _FakeDB(SimpleNamespace(avatar_url="https://existing.jpg"))
    sender = _FakeSender(OAUserProfile(avatar_url="x", display_name="y"))
    service = _make_service(
        db,
        sender,
        {"avatar_url": "https://existing.jpg", "name": None},
        contact,
    )

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is False
    assert sender.call_count == 0


async def test_stores_any_oa_label_on_contact_and_avatar_on_lead() -> None:
    contact = SimpleNamespace(display_name=None, avatar_url=None)
    saved_lead = SimpleNamespace(avatar_url=None)
    db = _FakeDB(saved_lead)
    sender = _FakeSender(
        OAUserProfile(avatar_url="https://zalo.me/a.jpg", display_name="Bé Gấu")
    )
    service = _make_service(db, sender, {"avatar_url": None, "name": None}, contact)

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is True
    assert contact.display_name == "Bé Gấu"
    assert contact.avatar_url == "https://zalo.me/a.jpg"
    assert saved_lead.avatar_url == "https://zalo.me/a.jpg"
    assert db.committed is True


async def test_profile_label_never_overwrites_confirmed_lead_name() -> None:
    contact = SimpleNamespace(display_name=None, avatar_url=None)
    saved_lead = SimpleNamespace(
        name="Tên ứng viên đã xác nhận",
        avatar_url=None,
    )
    db = _FakeDB(saved_lead)
    sender = _FakeSender(
        OAUserProfile(avatar_url="https://zalo.me/a.jpg", display_name="Tên Zalo")
    )
    service = _make_service(
        db,
        sender,
        {"avatar_url": None, "name": saved_lead.name},
        contact,
    )

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is True
    assert contact.display_name == "Tên Zalo"
    assert saved_lead.name == "Tên ứng viên đã xác nhận"


async def test_transport_error_is_retryable(monkeypatch) -> None:
    released = []

    async def release(zalo_id, owner):
        released.append((zalo_id, owner))

    monkeypatch.setattr("app.services.profile_enrichment._release_profile_lookup", release)
    contact = SimpleNamespace(display_name=None, avatar_url=None)
    db = _FakeDB(SimpleNamespace(avatar_url=None))
    sender = _FakeSender(None, raises=True)
    service = _make_service(db, sender, {"avatar_url": None, "name": None}, contact)

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is False
    assert db.committed is False
    assert released == [("oa:u1", "owner")]


async def test_missing_lead_or_contact_skips_provider() -> None:
    sender = _FakeSender(OAUserProfile(avatar_url="x", display_name="Any Label"))
    service = _make_service(_FakeDB(), sender, None, None)

    assert await service.enrich_oa_user("oa:missing", user_id="missing") is False
    assert sender.call_count == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Bé   Gấu  ", "Bé Gấu"),
        ("Shop Hoa", "Shop Hoa"),
        ("Nguyễn Văn Tí", "Nguyễn Văn Tí"),
        (None, ""),
    ],
)
async def test_display_name_cleanup_does_not_make_semantic_judgments(
    value: str | None,
    expected: str,
) -> None:
    assert normalize_oa_profile_display_name(value) == expected


async def test_empty_profile_stays_retryable(monkeypatch) -> None:
    contact = SimpleNamespace(display_name=None, avatar_url=None)
    db = _FakeDB(SimpleNamespace(avatar_url=None))
    sender = _FakeSender(OAUserProfile(avatar_url="", display_name=""))
    service = _make_service(db, sender, {"avatar_url": None, "name": None}, contact)

    assert await service.enrich_oa_user("oa:u1", user_id="u1") is False
    assert await service.enrich_oa_user("oa:u1", user_id="u1") is False
    assert sender.call_count == 2


async def test_partial_backfill_never_overwrites_contact_or_other_lead() -> None:
    contact = SimpleNamespace(
        id="contact-id", display_name="Recruiter label", avatar_url="https://kept.jpg"
    )
    saved_lead = SimpleNamespace(id=1, avatar_url=None, name="Confirmed")
    complete_lead = SimpleNamespace(id=2, avatar_url="https://other.jpg", name="Other")
    db = _FakeDB(saved_lead)
    db.leads.append(complete_lead)
    service = _make_service(
        db,
        _FakeSender(OAUserProfile(avatar_url="https://new.jpg", display_name="Zalo label")),
        {"avatar_url": None, "name": "Confirmed"},
        contact,
    )

    assert await service.enrich_oa_user("oa:u1", user_id="u1") is True
    assert contact.display_name == "Recruiter label"
    assert contact.avatar_url == "https://kept.jpg"
    assert saved_lead.avatar_url == "https://new.jpg"
    assert complete_lead.avatar_url == "https://other.jpg"


async def test_worker_wait_option_is_forwarded_to_lookup_guard(monkeypatch) -> None:
    wait_values = []

    async def claim(_zalo_id: str, *, wait_for_inflight: bool):
        wait_values.append(wait_for_inflight)
        return False, None

    monkeypatch.setattr("app.services.profile_enrichment._claim_profile_lookup", claim)
    contact = SimpleNamespace(display_name=None, avatar_url=None)
    service = _make_service(
        _FakeDB(SimpleNamespace(avatar_url=None)),
        _FakeSender(None),
        {"avatar_url": None, "name": None},
        contact,
    )

    await service.enrich_oa_user("oa:u1", user_id="u1", wait_for_inflight=True)

    assert wait_values == [True]
