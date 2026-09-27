"""Tests for Messenger contact-profile enrichment.

Covers ``ProfileEnrichmentService.enrich_messenger_user`` with fakes: the
blank-only write guards, the gender allow-list, the settled done-marker, and
the realtime emits for touched leads.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.services.profile_enrichment import ProfileEnrichmentService

pytestmark = pytest.mark.asyncio

_PAGE_ID = "page-1"
_PSID = "psid-1"


class _FakeConversations:
    def __init__(self, contact) -> None:
        self._conversation = SimpleNamespace(contact=contact) if contact else None

    async def get_by_identity(self, provider, account_key, external_id):
        assert provider == "facebook_messenger"
        assert account_key == _PAGE_ID
        assert external_id == _PSID
        return self._conversation


class _FakeDB:
    def __init__(self, *, contact, leads) -> None:
        self.contact = contact
        self.leads = list(leads)
        self.commits = 0
        self.gender_writes: dict[int, str] = {}
        self.avatar_lead_writes: dict[int, str] = {}

    async def commit(self) -> None:
        self.commits += 1

    async def select_contact(self, _contact_id, *, populate_existing: bool = False):
        return self.contact

    async def select_leads(self, _contact_id, *, populate_existing: bool = False):
        return list(self.leads)

    async def set_contact_display_name_if_blank(self, _contact_id, display_name: str) -> bool:
        if not _is_blank(self.contact.display_name):
            return False
        self.contact.display_name = display_name
        return True

    async def set_contact_avatar_if_blank(self, _contact_id, avatar_url: str) -> bool:
        if not _is_blank(self.contact.avatar_url):
            return False
        self.contact.avatar_url = avatar_url
        return True

    async def set_lead_avatars_if_blank(self, _contact_id, avatar_url: str) -> list[int]:
        updated_ids: list[int] = []
        for lead in self.leads:
            if _is_blank(lead.avatar_url):
                lead.avatar_url = avatar_url
                self.avatar_lead_writes[lead.id] = avatar_url
                updated_ids.append(lead.id)
        return updated_ids

    async def set_lead_genders_if_blank(self, _contact_id, gender: str) -> list[int]:
        updated_ids: list[int] = []
        for lead in self.leads:
            if _is_blank(lead.gender):
                lead.gender = gender
                self.gender_writes[lead.id] = gender
                updated_ids.append(lead.id)
        return updated_ids


class _FakeFetcher:
    def __init__(self, profile) -> None:
        self._profile = profile
        self.call_count = 0
        self.called_with: str | None = None

    async def __call__(self, psid: str):
        self.call_count += 1
        self.called_with = psid
        return self._profile


def _is_blank(value: str | None) -> bool:
    return not str(value or "").strip()


def _contact(**overrides):
    fields = {
        "id": "contact-id",
        "display_name": None,
        "avatar_url": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _lead(**overrides):
    fields = {
        "id": 1,
        "avatar_url": None,
        "gender": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _profile(**overrides):
    fields = {
        "display_name": "Bé Gấu",
        "profile_pic": "https://cdn.fb/a.jpg",
        "gender": "male",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.fixture(autouse=True)
def _profile_lookup_guard(monkeypatch):
    async def claim(_psid, *, wait_for_inflight, ignore_done=False, namespace=None):
        return True, "owner"

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.profile_enrichment._claim_profile_lookup", claim)
    monkeypatch.setattr("app.services.profile_enrichment._mark_profile_lookup_done", no_op)
    monkeypatch.setattr("app.services.profile_enrichment._release_profile_lookup", no_op)
    monkeypatch.setattr("app.services.profile_enrichment.LeadEventBus.lead_updated", no_op)


def _make_service(*, db, fetcher, contact) -> ProfileEnrichmentService:
    service = ProfileEnrichmentService.__new__(ProfileEnrichmentService)
    service.db = db  # type: ignore[assignment]
    service._conversations = _FakeConversations(contact)  # type: ignore[assignment]
    service._select_contact = db.select_contact  # type: ignore[method-assign]
    service._select_leads = db.select_leads  # type: ignore[method-assign]
    service._set_contact_display_name_if_blank = (  # type: ignore[method-assign]
        db.set_contact_display_name_if_blank
    )
    service._set_contact_avatar_if_blank = db.set_contact_avatar_if_blank  # type: ignore[method-assign]
    service._set_lead_avatars_if_blank = db.set_lead_avatars_if_blank  # type: ignore[method-assign]
    service._set_lead_genders_if_blank = db.set_lead_genders_if_blank  # type: ignore[method-assign]
    return service


async def test_happy_path_writes_blank_fields_settles_and_emits(monkeypatch) -> None:
    done_markers: list[str] = []
    emitted_lead_ids: list[int] = []

    async def mark_done(psid, *, namespace=None):
        done_markers.append(psid)

    async def emit(_self, lead):
        emitted_lead_ids.append(lead.id)

    monkeypatch.setattr(
        "app.services.profile_enrichment._mark_profile_lookup_done", mark_done
    )
    monkeypatch.setattr(
        "app.services.profile_enrichment.LeadEventBus.lead_updated", emit
    )

    contact = _contact()
    lead = _lead()
    db = _FakeDB(contact=contact, leads=[lead])
    fetcher = _FakeFetcher(_profile())
    service = _make_service(db=db, fetcher=fetcher, contact=contact)

    result = await service.enrich_messenger_user(
        _PSID,
        page_id=_PAGE_ID,
        fetch_profile=fetcher,
    )

    assert result is True
    assert contact.display_name == "Bé Gấu"
    assert contact.avatar_url == "https://cdn.fb/a.jpg"
    assert lead.avatar_url == "https://cdn.fb/a.jpg"
    assert lead.gender == "male"
    assert db.commits == 1
    assert done_markers == [_PSID]
    assert emitted_lead_ids == [1]
    assert fetcher.call_count == 1
    assert fetcher.called_with == _PSID


async def test_invalid_provider_gender_is_never_written() -> None:
    contact = _contact(avatar_url="https://x/y.jpg")
    lead = _lead()
    db = _FakeDB(contact=contact, leads=[lead])
    fetcher = _FakeFetcher(_profile(profile_pic="", gender="invisible"))
    service = _make_service(db=db, fetcher=fetcher, contact=contact)

    result = await service.enrich_messenger_user(
        _PSID, page_id=_PAGE_ID, fetch_profile=fetcher
    )

    assert result is True
    assert contact.display_name == "Bé Gấu"
    assert lead.avatar_url is None
    assert lead.gender is None
    assert db.gender_writes == {}
    assert db.commits == 1


async def test_nothing_missing_never_calls_the_provider() -> None:
    contact = _contact(display_name="Bé Gấu", avatar_url="https://x/y.jpg")
    lead = _lead(avatar_url="https://x/z.jpg", gender="female")
    db = _FakeDB(contact=contact, leads=[lead])
    fetcher = _FakeFetcher(None)
    service = _make_service(db=db, fetcher=fetcher, contact=contact)

    result = await service.enrich_messenger_user(
        _PSID, page_id=_PAGE_ID, fetch_profile=fetcher
    )

    assert result is False
    assert fetcher.call_count == 0
    assert db.commits == 0


async def test_stated_gender_is_never_overwritten_by_profile() -> None:
    contact = _contact(display_name="Đã có", avatar_url="https://x/y.jpg")
    lead = _lead(avatar_url="https://x/z.jpg", gender="female")
    db = _FakeDB(contact=contact, leads=[lead])
    fetcher = _FakeFetcher(_profile(gender="male"))
    service = _make_service(db=db, fetcher=fetcher, contact=contact)

    result = await service.enrich_messenger_user(
        _PSID, page_id=_PAGE_ID, fetch_profile=fetcher
    )

    assert result is False
    assert db.gender_writes == {}
    assert lead.gender == "female"
    assert db.commits == 0


async def test_empty_profile_keeps_lookup_retryable() -> None:
    contact = _contact()
    lead = _lead()
    db = _FakeDB(contact=contact, leads=[lead])
    fetcher = _FakeFetcher(_profile(display_name="", profile_pic="", gender=""))
    service = _make_service(db=db, fetcher=fetcher, contact=contact)

    result = await service.enrich_messenger_user(
        _PSID, page_id=_PAGE_ID, fetch_profile=fetcher
    )

    assert result is False
    assert db.gender_writes == {}
    assert db.commits == 0
    assert lead.avatar_url is None
    assert lead.gender is None
