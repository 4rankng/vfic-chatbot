"""Data-access layer for leads.

Owns all raw SQL: the COALESCE-based upsert, fetch, materialize, events, and
follow-ups.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import FollowUpTask, Lead, LeadEvent, LeadTag

# ── Raw SQL constants ──────────────────────────────────────────────

_FETCH_SQL = text(
    """
    SELECT id, zalo_id, name, phone, birth_year, age, living_area, address, gender,
           region, desired_job, years_experience, expected_salary, avatar_url,
           lead_score, lead_stage, notes, version
    FROM leads WHERE zalo_id = :zalo_id
    """
)

_UPSQL = text(
    """
    INSERT INTO leads (zalo_id, name, phone, birth_year, age, living_area, address, gender,
        region, desired_job, years_experience, expected_salary, lead_score,
        notes, version)
    VALUES (:zalo_id, :name, :phone, :birth_year, :age, :living_area, :address, :gender,
        :region, :desired_job, :years_experience, :expected_salary, :lead_score,
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
        expected_salary = COALESCE(NULLIF(EXCLUDED.expected_salary,''), leads.expected_salary),
        lead_score = COALESCE(EXCLUDED.lead_score, leads.lead_score),
        notes = CASE
            WHEN EXCLUDED.notes IS NULL OR EXCLUDED.notes = '' THEN leads.notes
            WHEN leads.notes IS NULL OR leads.notes = '' THEN EXCLUDED.notes
            ELSE concat_ws(
                E'\n',
                leads.notes,
                (
                    SELECT string_agg(incoming.note, E'\n' ORDER BY incoming.line_order)
                    FROM (
                        SELECT btrim(split.line) AS note, split.line_order
                        FROM regexp_split_to_table(EXCLUDED.notes, chr(10))
                             WITH ORDINALITY AS split(line, line_order)
                    ) AS incoming
                    WHERE incoming.note <> ''
                      AND NOT EXISTS (
                          SELECT 1
                          FROM regexp_split_to_table(leads.notes, chr(10)) AS stored(line)
                          WHERE lower(
                              regexp_replace(
                                  regexp_replace(btrim(stored.line), '[[:space:]]+', ' ', 'g'),
                                  '[.!?;:,]+$',
                                  '',
                                  'g'
                              )
                          ) = lower(
                              regexp_replace(
                                  regexp_replace(incoming.note, '[[:space:]]+', ' ', 'g'),
                                  '[.!?;:,]+$',
                                  '',
                                  'g'
                              )
                          )
                      )
                )
            )
        END,
        version = leads.version + 1,
        updated_at = now()
    RETURNING id
    """
)

_SET_GENDER_BY_ID_SQL = text(
    """
    UPDATE leads
    SET gender = :gender
    WHERE id = :lead_id
    RETURNING id
    """
)

# Messenger rows are keyed by ``contact_id`` with a NULL ``zalo_id`` (migration
# 0047), so a chat-id lookup never finds them. The latest lead for the contact
# wins — multiple leads may share a contact, and the stub trigger only dedups
# NEW-stage rows.
_BY_CONTACT_SQL = text(
    """
    SELECT id, zalo_id, name, phone, birth_year, age, living_area, address, gender,
           region, desired_job, years_experience, expected_salary, avatar_url,
           lead_score, lead_stage, notes, version
    FROM leads WHERE contact_id = CAST(:contact_id AS uuid)
    ORDER BY updated_at DESC, id DESC
    LIMIT 1
    """
)

# ── Repository ─────────────────────────────────────────────────────


class LeadRepository:
    """Raw-SQL lead persistence."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert(self, lead: dict) -> int | None:
        """Insert or merge a normalised lead by ``zalo_id``; return the lead id."""
        row = await self.db.execute(_UPSQL, lead)
        await self.db.flush()
        return row.scalar()

    async def by_zalo_id(self, zalo_id: str) -> dict | None:
        """Fetch an existing lead by ``zalo_id``; return all columns as a dict, or None."""
        row = await self.db.execute(_FETCH_SQL, {"zalo_id": zalo_id})
        result = row.mappings().first()
        return dict(result) if result else None

    async def set_gender_by_id(self, lead_id: int, gender: str) -> bool:
        """Write a gender onto a lead by primary key; True when a row was updated.

        The blank-only guard lives in the adapter, which reads the row first, so
        a stated/provider/CRM value is preserved unless the caller explicitly
        overrides it (a candidate self-referring in the current message).
        ``version`` and ``updated_at`` are deliberately untouched — this is
        background enrichment, not a user-visible edit.
        """
        result = await self.db.execute(
            _SET_GENDER_BY_ID_SQL, {"lead_id": lead_id, "gender": gender}
        )
        return result.scalar_one_or_none() is not None

    async def by_contact_id(self, contact_id: str) -> dict | None:
        """Latest lead for a contact; None when the contact has no lead."""
        row = await self.db.execute(_BY_CONTACT_SQL, {"contact_id": str(contact_id)})
        result = row.mappings().first()
        return dict(result) if result else None

    async def optimistic_apply(self, lead_id: int, current_version: int, **values) -> bool:
        """Execute optimistic-concurrency update + commit. Returns True if row was updated.

        The caller handles ``ConflictError`` on False and performs post-update refresh
        and business logic (events, audit). The double-commit pattern in assign/set_stage
        is preserved by the caller committing events/audit separately.
        """
        from sqlalchemy import update

        res = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead_id,
                Lead.version == current_version,
            )
            .values(**values, updated_at=func.now())
            .execution_options(synchronize_session=False)
        )
        await self.db.flush()
        return res.rowcount > 0

    async def list_events(self, lead_id: int, *, limit: int = 200) -> list[LeadEvent]:
        return list(
            (
                await self.db.scalars(
                    select(LeadEvent)
                    .where(LeadEvent.lead_id == lead_id)
                    .order_by(desc(LeadEvent.created_at))
                    .limit(limit)
                )
            ).all()
        )

    async def list_followups(self, lead_id: int, *, limit: int = 200) -> list[FollowUpTask]:
        return list(
            (
                await self.db.scalars(
                    select(FollowUpTask)
                    .where(FollowUpTask.lead_id == lead_id)
                    .order_by(FollowUpTask.due_at)
                    .limit(limit)
                )
            ).all()
        )

    async def create_followup(
        self, lead_id: int, due_at: datetime, note: str | None, created_by
    ) -> FollowUpTask:
        fu = FollowUpTask(lead_id=lead_id, due_at=due_at, note=note, created_by=created_by)
        self.db.add(fu)
        await self.db.flush()
        await self.db.refresh(fu)
        return fu

    async def list_manual_tags(self, lead_id: int) -> list[LeadTag]:
        return list(
            (
                await self.db.scalars(
                    select(LeadTag).where(LeadTag.lead_id == lead_id).order_by(LeadTag.key)
                )
            ).all()
        )

    async def replace_manual_tags(
        self,
        lead_id: int,
        tag_payloads: list[dict[str, str]],
        *,
        created_by,
    ) -> list[LeadTag]:
        next_keys = {payload["key"] for payload in tag_payloads}
        if next_keys:
            await self.db.execute(
                delete(LeadTag)
                .where(LeadTag.lead_id == lead_id)
                .where(LeadTag.key.not_in(next_keys))
            )
        else:
            await self.db.execute(delete(LeadTag).where(LeadTag.lead_id == lead_id))

        existing = {tag.key: tag for tag in await self.list_manual_tags(lead_id)}
        for payload in tag_payloads:
            current = existing.get(payload["key"])
            if current is None:
                self.db.add(
                    LeadTag(
                        lead_id=lead_id,
                        key=payload["key"],
                        label=payload["label"],
                        tone=payload["tone"],
                        created_by=created_by,
                    )
                )
                continue
            current.label = payload["label"]
            current.tone = payload["tone"]
        await self.db.flush()
        return await self.list_manual_tags(lead_id)


__all__ = ["LeadRepository"]
