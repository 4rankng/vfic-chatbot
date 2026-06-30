"""Data-access layer for leads.

Owns the COALESCE-based upsert the ORM cannot express: a non-empty existing value
is never overwritten with null/empty (the live 'Merge Lead' behavior). Verbatim
port of the SQL that lived in ``lead_service._UPSQL``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import FollowUpTask, Lead, LeadEvent


class LeadRepository:
    """Raw-SQL lead persistence."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert(self, lead: dict) -> int | None:
        """Insert or merge a normalised lead by ``zalo_id``; return the lead id."""
        row = await self.db.execute(_UPSQL, lead)
        await self.db.commit()
        return row.scalar()

    async def by_zalo_id(self, zalo_id: str) -> dict | None:
        """Fetch an existing lead by ``zalo_id``; return all columns as a dict, or None."""
        row = await self.db.execute(_FETCH_SQL, {"zalo_id": zalo_id})
        result = row.mappings().first()
        return dict(result) if result else None

    async def optimistic_apply(self, lead_id: int, current_version: int, **values) -> bool:
        """Execute optimistic-concurrency update + commit. Returns True if row was updated.

        The caller handles ``LeadConflict`` on False and performs post-update refresh
        and business logic (events, audit). The double-commit pattern in assign/set_stage
        is preserved by the caller committing events/audit separately.
        """
        res = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead_id,
                Lead.version == current_version,
            )
            .values(**values, updated_at=func.now())
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return res.rowcount > 0

    async def list_events(self, lead_id: int) -> list[LeadEvent]:
        return list(
            (
                await self.db.scalars(
                    select(LeadEvent)
                    .where(LeadEvent.lead_id == lead_id)
                    .order_by(desc(LeadEvent.created_at))
                )
            ).all()
        )

    async def list_followups(self, lead_id: int) -> list[FollowUpTask]:
        return list(
            (
                await self.db.scalars(
                    select(FollowUpTask)
                    .where(FollowUpTask.lead_id == lead_id)
                    .order_by(FollowUpTask.due_at)
                )
            ).all()
        )

    async def create_followup(
        self, lead_id: int, due_at: datetime, note: str | None, created_by
    ) -> FollowUpTask:
        fu = FollowUpTask(lead_id=lead_id, due_at=due_at, note=note, created_by=created_by)
        self.db.add(fu)
        await self.db.commit()
        await self.db.refresh(fu)
        return fu


_FETCH_SQL = text(
    """
    SELECT id, zalo_id, name, phone, birth_year, age, living_area, address, gender,
           region, desired_job, years_experience, latest_company, expected_salary,
           lead_score, lead_stage, notes, version
    FROM leads WHERE zalo_id = :zalo_id
    """
)


_UPSQL = text(
    """
    INSERT INTO leads (zalo_id, name, phone, birth_year, age, living_area, address, gender,
        region, desired_job, years_experience, latest_company, expected_salary, lead_score,
        notes, version)
    VALUES (:zalo_id, :name, :phone, :birth_year, :age, :living_area, :address, :gender,
        :region, :desired_job, :years_experience, :latest_company, :expected_salary, :lead_score,
        :notes, 1)
    ON CONFLICT (zalo_id) DO UPDATE SET
        name = COALESCE(NULLIF(EXCLUDED.name,''), leads.name),
        phone = COALESCE(NULLIF(EXCLUDED.phone,''), leads.phone),
        birth_year = COALESCE(EXCLUDED.birth_year, leads.birth_year),
        age = COALESCE(EXCLUDED.age, leads.age),
        living_area = COALESCE(NULLIF(EXCLUDED.living_area,''), leads.living_area),
        address = COALESCE(NULLIF(EXCLUDED.address,''), leads.address),
        gender = COALESCE(NULLIF(EXCLUDED.gender,''), leads.gender),
        region = COALESCE(NULLIF(EXCLUDED.region,''), leads.region),
        desired_job = COALESCE(NULLIF(EXCLUDED.desired_job,''), leads.desired_job),
        years_experience = COALESCE(NULLIF(EXCLUDED.years_experience,''), leads.years_experience),
        latest_company = COALESCE(NULLIF(EXCLUDED.latest_company,''), leads.latest_company),
        expected_salary = COALESCE(NULLIF(EXCLUDED.expected_salary,''), leads.expected_salary),
        lead_score = COALESCE(EXCLUDED.lead_score, leads.lead_score),
        notes = CASE
            WHEN EXCLUDED.notes IS NULL OR EXCLUDED.notes = '' THEN leads.notes
            WHEN leads.notes IS NULL THEN EXCLUDED.notes
            WHEN position(lower(EXCLUDED.notes) IN lower(leads.notes)) > 0
                 OR position(lower(leads.notes) IN lower(EXCLUDED.notes)) > 0
            THEN leads.notes
            ELSE leads.notes || E'\n' || EXCLUDED.notes
        END,
        version = leads.version + 1,
        updated_at = now()
    RETURNING id
    """
)


__all__ = ["LeadRepository"]
