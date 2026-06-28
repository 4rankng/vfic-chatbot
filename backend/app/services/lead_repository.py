"""Data-access layer for leads.

Owns the COALESCE-based upsert the ORM cannot express: a non-empty existing value
is never overwritten with null/empty (the live 'Merge Lead' behavior). Verbatim
port of the SQL that lived in ``lead_service._UPSQL``.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class LeadRepository:
    """Raw-SQL lead persistence."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert(self, lead: dict) -> int | None:
        """Insert or merge a normalised lead by ``zalo_id``; return the lead id."""
        row = await self.db.execute(_UPSQL, lead)
        await self.db.commit()
        return row.scalar()


_UPSQL = text(
    """
    INSERT INTO leads (zalo_id, name, phone, birth_year, age, living_area, address, gender,
        region, desired_job, years_experience, latest_company, expected_salary, lead_score)
    VALUES (:zalo_id, :name, :phone, :birth_year, :age, :living_area, :address, :gender,
        :region, :desired_job, :years_experience, :latest_company, :expected_salary, :lead_score)
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
        updated_at = now()
    RETURNING id
    """
)


__all__ = ["LeadRepository"]
