"""Tests for OA contact-profile enrichment."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.profile_enrichment import (
    ProfileEnrichmentService,
    _claim_profile_lookup,
    normalize_oa_profile_display_name,
)
from app.services.zalo_oa_service import OAUserProfile

pytestmark = pytest.mark.asyncio


async def test_force_lookup_skips_done_marker_and_still_claims_lock(monkeypatch) -> None:
    class FakeRedis:
        async def exists(self, _key):
            return True

        async def set(self, _key, _value, **kwargs):
            assert kwargs["nx"] is True
            assert kwargs["ex"] > 0
            return True

    monkeypatch.setattr("app.core.redis.get_redis", lambda: FakeRedis())

    assert await _claim_profile_lookup(
        "oa:u1", wait_for_inflight=True, ignore_done=False
    ) == (False, None)
    claimed, owner = await _claim_profile_lookup(
        "oa:u1", wait_for_inflight=True, ignore_done=True
    )
    assert claimed is True
    assert owner is not None


def _is_blank(value: str | None) -> bool:
    return not str(value or "").strip()


class _FakeConversations:
    def __init__(self, contact) -> None:
        self._conversation = SimpleNamespace(contact=contact) if contact else None

    async def get_by_zalo(self, _zalo_id: str):
        return self._conversation


class _FakeDB:
    def __init__(
        self,
        *,
        current_contact=None,
        initial_leads=None,
        current_leads=None,
    ) -> None:
        self.current_contact = current_contact
        self.initial_leads = list(initial_leads or [])
        self.current_leads = list(
            current_leads if current_leads is not None else self.initial_leads
        )
        self.commits = 0
        self.lead_select_calls = 0
        self.contact_select_populate_existing: list[bool] = []
        self.lead_select_populate_existing: list[bool] = []

    async def commit(self) -> None:
        self.commits += 1

    async def select_contact(self, _contact_id, *, populate_existing: bool = False):
        self.contact_select_populate_existing.append(populate_existing)
        return self.current_contact

    async def select_leads(self, _contact_id, *, populate_existing: bool = False):
        self.lead_select_calls += 1
        self.lead_select_populate_existing.append(populate_existing)
        if self.lead_select_calls == 1:
            return list(self.initial_leads)
        return list(self.current_leads)

    async def set_contact_display_name_if_blank(self, _contact_id, display_name: str) -> bool:
        if self.current_contact is None or not _is_blank(self.current_contact.display_name):
            return False
        self.current_contact.display_name = display_name
        return True

    async def set_contact_avatar_if_blank(self, _contact_id, avatar_url: str) -> bool:
        if self.current_contact is None or not _is_blank(self.current_contact.avatar_url):
            return False
        self.current_contact.avatar_url = avatar_url
        return True

    async def set_lead_avatars_if_blank(self, _contact_id, avatar_url: str) -> list[int]:
        updated_ids: list[int] = []
        for lead in self.current_leads:
            if _is_blank(lead.avatar_url):
                lead.avatar_url = avatar_url
                updated_ids.append(lead.id)
        return updated_ids


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
    async def claim(_zalo_id: str, *, wait_for_inflight: bool, ignore_done: bool = False):
        return True, "owner"

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.profile_enrichment._claim_profile_lookup", claim)
    monkeypatch.setattr("app.services.profile_enrichment._mark_profile_lookup_done", no_op)
    monkeypatch.setattr("app.services.profile_enrichment._release_profile_lookup", no_op)
    monkeypatch.setattr("app.services.profile_enrichment.LeadEventBus.lead_updated", no_op)


def _make_service(
    *,
    db: _FakeDB,
    sender: _FakeSender,
    conversation_contact,
) -> ProfileEnrichmentService:
    if conversation_contact is not None and not hasattr(conversation_contact, "id"):
        conversation_contact.id = "contact-id"
    service = ProfileEnrichmentService.__new__(ProfileEnrichmentService)
    service.db = db  # type: ignore[assignment]
    service.sender = sender  # type: ignore[assignment]
    service._conversations = _FakeConversations(conversation_contact)  # type: ignore[assignment]
    service._select_contact = db.select_contact  # type: ignore[method-assign]
    service._select_leads = db.select_leads  # type: ignore[method-assign]
    service._set_contact_display_name_if_blank = (  # type: ignore[method-assign]
        db.set_contact_display_name_if_blank
    )
    service._set_contact_avatar_if_blank = db.set_contact_avatar_if_blank  # type: ignore[method-assign]
    service._set_lead_avatars_if_blank = db.set_lead_avatars_if_blank  # type: ignore[method-assign]
    return service


async def test_short_circuits_when_contact_profile_is_complete() -> None:
    contact = SimpleNamespace(id="contact-id", display_name="Bé Gấu", avatar_url="https://existing.jpg")
    lead = SimpleNamespace(id=1, avatar_url="https://existing.jpg")
    db = _FakeDB(current_contact=contact, initial_leads=[lead])
    sender = _FakeSender(OAUserProfile(avatar_url="x", display_name="y"))
    service = _make_service(db=db, sender=sender, conversation_contact=contact)

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is False
    assert sender.call_count == 0
    assert db.commits == 0


async def test_stores_any_oa_label_on_contact_and_avatar_on_blank_leads() -> None:
    snapshot_contact = SimpleNamespace(id="contact-id", display_name=None, avatar_url=None)
    current_contact = SimpleNamespace(id="contact-id", display_name=None, avatar_url=None)
    current_lead = SimpleNamespace(id=1, avatar_url=None)
    db = _FakeDB(
        current_contact=current_contact,
        initial_leads=[SimpleNamespace(id=1, avatar_url=None)],
        current_leads=[current_lead],
    )
    sender = _FakeSender(
        OAUserProfile(avatar_url="https://zalo.me/a.jpg", display_name="Bé Gấu")
    )
    service = _make_service(db=db, sender=sender, conversation_contact=snapshot_contact)

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is True
    assert current_contact.display_name == "Bé Gấu"
    assert current_contact.avatar_url == "https://zalo.me/a.jpg"
    assert current_lead.avatar_url == "https://zalo.me/a.jpg"
    assert db.commits == 1


async def test_profile_label_never_overwrites_confirmed_lead_name() -> None:
    snapshot_contact = SimpleNamespace(id="contact-id", display_name=None, avatar_url=None)
    current_contact = SimpleNamespace(id="contact-id", display_name=None, avatar_url=None)
    current_lead = SimpleNamespace(
        id=1,
        name="Tên ứng viên đã xác nhận",
        avatar_url=None,
    )
    db = _FakeDB(
        current_contact=current_contact,
        initial_leads=[SimpleNamespace(id=1, name=current_lead.name, avatar_url=None)],
        current_leads=[current_lead],
    )
    sender = _FakeSender(
        OAUserProfile(avatar_url="https://zalo.me/a.jpg", display_name="Tên Zalo")
    )
    service = _make_service(db=db, sender=sender, conversation_contact=snapshot_contact)

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is True
    assert current_contact.display_name == "Tên Zalo"
    assert current_lead.name == "Tên ứng viên đã xác nhận"


async def test_transport_error_is_retryable(monkeypatch) -> None:
    released = []

    async def release(zalo_id, owner):
        released.append((zalo_id, owner))

    monkeypatch.setattr("app.services.profile_enrichment._release_profile_lookup", release)
    contact = SimpleNamespace(id="contact-id", display_name=None, avatar_url=None)
    db = _FakeDB(
        current_contact=contact,
        initial_leads=[SimpleNamespace(id=1, avatar_url=None)],
    )
    sender = _FakeSender(None, raises=True)
    service = _make_service(db=db, sender=sender, conversation_contact=contact)

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is False
    assert db.commits == 0
    assert released == [("oa:u1", "owner")]


async def test_missing_lead_or_contact_skips_provider() -> None:
    sender = _FakeSender(OAUserProfile(avatar_url="x", display_name="Any Label"))
    service = _make_service(
        db=_FakeDB(current_contact=None, initial_leads=[]),
        sender=sender,
        conversation_contact=None,
    )

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


async def test_empty_profile_stays_retryable() -> None:
    contact = SimpleNamespace(id="contact-id", display_name=None, avatar_url=None)
    db = _FakeDB(
        current_contact=contact,
        initial_leads=[SimpleNamespace(id=1, avatar_url=None)],
    )
    sender = _FakeSender(OAUserProfile(avatar_url="", display_name=""))
    service = _make_service(db=db, sender=sender, conversation_contact=contact)

    assert await service.enrich_oa_user("oa:u1", user_id="u1") is False
    assert await service.enrich_oa_user("oa:u1", user_id="u1") is False
    assert sender.call_count == 2


async def test_partial_backfill_updates_only_blank_leads_and_emits_only_them(monkeypatch) -> None:
    updated_ids: list[int] = []

    async def lead_updated(_self, lead, *, actor_name: str | None = None) -> None:
        assert actor_name is None
        updated_ids.append(lead.id)

    monkeypatch.setattr("app.services.profile_enrichment.LeadEventBus.lead_updated", lead_updated)
    snapshot_contact = SimpleNamespace(
        id="contact-id",
        display_name="Recruiter label",
        avatar_url="https://kept.jpg",
    )
    current_contact = SimpleNamespace(
        id="contact-id",
        display_name="Recruiter label",
        avatar_url="https://kept.jpg",
    )
    current_leads = [
        SimpleNamespace(id=1, avatar_url=None, name="Confirmed"),
        SimpleNamespace(id=2, avatar_url="https://other.jpg", name="Other"),
    ]
    db = _FakeDB(
        current_contact=current_contact,
        initial_leads=[
            SimpleNamespace(id=1, avatar_url=None, name="Confirmed"),
            SimpleNamespace(id=2, avatar_url="https://other.jpg", name="Other"),
        ],
        current_leads=current_leads,
    )
    service = _make_service(
        db=db,
        sender=_FakeSender(
            OAUserProfile(avatar_url="https://new.jpg", display_name="Zalo label")
        ),
        conversation_contact=snapshot_contact,
    )

    assert await service.enrich_oa_user("oa:u1", user_id="u1") is True
    assert current_contact.display_name == "Recruiter label"
    assert current_contact.avatar_url == "https://kept.jpg"
    assert current_leads[0].avatar_url == "https://new.jpg"
    assert current_leads[1].avatar_url == "https://other.jpg"
    assert updated_ids == [1]


async def test_stale_snapshot_never_overwrites_newer_values_and_marks_done(monkeypatch) -> None:
    marked_done: list[str] = []
    updated_ids: list[int] = []

    async def mark_done(zalo_id: str) -> None:
        marked_done.append(zalo_id)

    async def lead_updated(_self, lead, *, actor_name: str | None = None) -> None:
        updated_ids.append(lead.id)

    monkeypatch.setattr("app.services.profile_enrichment._mark_profile_lookup_done", mark_done)
    monkeypatch.setattr("app.services.profile_enrichment.LeadEventBus.lead_updated", lead_updated)
    snapshot_contact = SimpleNamespace(id="contact-id", display_name=None, avatar_url=None)
    current_contact = SimpleNamespace(
        id="contact-id",
        display_name="Admin set name",
        avatar_url="https://admin/avatar.jpg",
    )
    db = _FakeDB(
        current_contact=current_contact,
        initial_leads=[SimpleNamespace(id=1, avatar_url=None)],
        current_leads=[SimpleNamespace(id=1, avatar_url="https://admin/avatar.jpg")],
    )
    service = _make_service(
        db=db,
        sender=_FakeSender(
            OAUserProfile(
                avatar_url="https://zalo/avatar.jpg",
                display_name="Zalo name",
            )
        ),
        conversation_contact=snapshot_contact,
    )

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is False
    assert current_contact.display_name == "Admin set name"
    assert current_contact.avatar_url == "https://admin/avatar.jpg"
    assert db.commits == 0
    assert marked_done == ["oa:u1"]
    assert updated_ids == []
    assert db.contact_select_populate_existing == [True]
    assert db.lead_select_populate_existing == [False, True]


async def test_whitespace_values_are_treated_as_blank_for_atomic_updates() -> None:
    snapshot_contact = SimpleNamespace(id="contact-id", display_name="   ", avatar_url="  ")
    current_contact = SimpleNamespace(id="contact-id", display_name="   ", avatar_url="  ")
    current_lead = SimpleNamespace(id=1, avatar_url="   ")
    db = _FakeDB(
        current_contact=current_contact,
        initial_leads=[SimpleNamespace(id=1, avatar_url="   ")],
        current_leads=[current_lead],
    )
    service = _make_service(
        db=db,
        sender=_FakeSender(
            OAUserProfile(
                avatar_url="https://zalo/avatar.jpg",
                display_name="  Bé   Gấu  ",
            )
        ),
        conversation_contact=snapshot_contact,
    )

    result = await service.enrich_oa_user("oa:u1", user_id="u1")

    assert result is True
    assert current_contact.display_name == "Bé Gấu"
    assert current_contact.avatar_url == "https://zalo/avatar.jpg"
    assert current_lead.avatar_url == "https://zalo/avatar.jpg"
    assert db.commits == 1


async def test_worker_wait_option_is_forwarded_to_lookup_guard(monkeypatch) -> None:
    claim_options = []

    async def claim(_zalo_id: str, *, wait_for_inflight: bool, ignore_done: bool = False):
        claim_options.append((wait_for_inflight, ignore_done))
        return False, None

    monkeypatch.setattr("app.services.profile_enrichment._claim_profile_lookup", claim)
    contact = SimpleNamespace(id="contact-id", display_name=None, avatar_url=None)
    service = _make_service(
        db=_FakeDB(
            current_contact=contact,
            initial_leads=[SimpleNamespace(id=1, avatar_url=None)],
        ),
        sender=_FakeSender(None),
        conversation_contact=contact,
    )

    await service.enrich_oa_user("oa:u1", user_id="u1", wait_for_inflight=True)

    assert claim_options == [(True, False)]


async def test_maintenance_force_lookup_ignores_done_marker_but_keeps_lock(monkeypatch) -> None:
    claim_options = []

    async def claim(_zalo_id: str, *, wait_for_inflight: bool, ignore_done: bool = False):
        claim_options.append((wait_for_inflight, ignore_done))
        return False, None

    monkeypatch.setattr("app.services.profile_enrichment._claim_profile_lookup", claim)
    contact = SimpleNamespace(id="contact-id", display_name=None, avatar_url=None)
    service = _make_service(
        db=_FakeDB(
            current_contact=contact,
            initial_leads=[SimpleNamespace(id=1, avatar_url=None)],
        ),
        sender=_FakeSender(None),
        conversation_contact=contact,
    )

    await service.enrich_oa_user(
        "oa:u1",
        user_id="u1",
        wait_for_inflight=True,
        force_lookup=True,
    )

    assert claim_options == [(True, True)]
