"""A completed lead miss is reused throughout a candidate's first bot turn."""

from unittest.mock import AsyncMock

import pytest

from app.recruitment.infrastructure import service_adapters


@pytest.mark.asyncio
async def test_missing_prefetched_lead_is_reused_for_gender_read_and_write(monkeypatch):
    resolve = AsyncMock(return_value={"id": 9, "gender": "female"})
    monkeypatch.setattr(service_adapters, "_resolve_lead", resolve)
    adapter = service_adapters.ServiceLeadGenderAdapter(object())

    assert await adapter.stored_gender("candidate", lead=None) == ""
    assert await adapter.record_inferred_gender("candidate", "female", lead=None) is False
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_prefetched_lead_is_reused_for_profile_capture(monkeypatch):
    resolve = AsyncMock(return_value={"id": 9})
    persist = AsyncMock(return_value=True)
    monkeypatch.setattr(service_adapters, "_resolve_lead", resolve)
    monkeypatch.setattr(service_adapters, "_persist_profile_name_if_absent", persist)
    db = object()
    adapter = service_adapters.ServiceLeadGenderAdapter(db)

    assert await adapter.record_profile_name("oa:candidate", "Nguyễn Hùng", lead=None)
    resolve.assert_not_awaited()
    persist.assert_awaited_once_with(db, "oa:candidate", "Nguyễn Hùng", None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("lead", [None, {"id": 9, "name": "Nguyễn Hùng"}])
async def test_prefetched_lead_is_reused_for_prompt_context(monkeypatch, lead):
    resolve = AsyncMock()
    evidence = AsyncMock(return_value=lead)
    monkeypatch.setattr(service_adapters, "_resolve_lead", resolve)
    monkeypatch.setattr("app.services.lead.contact_evidence.contact_evidence_context", evidence)
    adapter = service_adapters.ServiceLeadContextAdapter(object())

    profile, guidance = await adapter.context("candidate", "Tôi muốn tìm việc", [], lead=lead)

    resolve.assert_not_awaited()
    assert isinstance(profile, str)
    assert isinstance(guidance, str)
    assert evidence.await_args.args[1] is lead


@pytest.mark.asyncio
async def test_unresolved_gender_read_keeps_repository_fallback(monkeypatch):
    resolve = AsyncMock(return_value={"id": 9, "gender": "female"})
    monkeypatch.setattr(service_adapters, "_resolve_lead", resolve)
    db = object()
    adapter = service_adapters.ServiceLeadGenderAdapter(db)

    assert await adapter.stored_gender("candidate", "contact") == "female"
    resolve.assert_awaited_once_with(db, "candidate", "contact")


@pytest.mark.asyncio
async def test_unresolved_prompt_context_keeps_repository_fallback(monkeypatch):
    resolve = AsyncMock(return_value=None)
    monkeypatch.setattr(service_adapters, "_resolve_lead", resolve)
    db = object()
    adapter = service_adapters.ServiceLeadContextAdapter(db)

    await adapter.context("candidate", "Tôi muốn tìm việc", [], contact_id="contact")

    resolve.assert_awaited_once_with(db, "candidate", "contact")
