"""Regression guard for the `lead_stage` PATCH concurrency hole (K-6).

`PATCH /leads/{id}` can change the stage *and* other fields at once. That runs
two service calls: `set_stage` first (which advances the row version), then
`update` for whatever remains.

The bug: the handler used to discard the caller's `version` after the stage
call. With no `version` in `changes`, `LeadService.update` takes its unchecked
"trusted internal caller" branch — it never calls `optimistic_apply`, so a
stale writer silently overwrites a concurrent edit.

The fix re-arms the guard with the version `set_stage` just produced.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.api.leads as leads_api
from app.schemas.lead import LeadStage, LeadUpdate


class _FakeService:
    """Records what the handler asks the follow-up write to do."""

    def __init__(self) -> None:
        self.update_changes: dict | None = None

    def __call__(self, _db):  # stands in for LeadService(db)
        return self

    async def set_stage(self, lead, stage, *, actor):  # noqa: ARG002
        # The real set_stage commits and refreshes, advancing the row version.
        lead.version += 1
        lead.lead_stage = stage
        return lead

    async def update(self, lead, changes):
        self.update_changes = dict(changes)
        return lead


@pytest.mark.asyncio
async def test_stage_change_rearms_concurrency_guard_for_remaining_fields(monkeypatch):
    service = _FakeService()
    lead = SimpleNamespace(id=1, version=3, name="old", lead_stage=LeadStage.NEW)

    monkeypatch.setattr(leads_api, "LeadService", service)
    monkeypatch.setattr(leads_api, "_load", AsyncMock(return_value=lead))
    monkeypatch.setattr(leads_api.LeadOut, "model_validate", staticmethod(lambda row: row))

    await leads_api.update_lead(
        lead_id=1,
        body=LeadUpdate(version=3, lead_stage=LeadStage.CONTACTING, name="edited"),
        user=SimpleNamespace(id=1, full_name="recruiter", role="admin"),
        db=MagicMock(),
    )

    assert service.update_changes is not None, "the non-stage fields must still be written"
    assert service.update_changes["name"] == "edited"
    assert service.update_changes["version"] == 4, (
        "the follow-up write must carry the version set_stage produced; without it "
        "LeadService.update skips optimistic_apply and concurrent edits are lost"
    )
