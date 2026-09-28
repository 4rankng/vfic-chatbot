"""Data-access layer for leads.

Owns all raw SQL: the COALESCE-based upsert, fetch, materialize, events, and
follow-ups.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, desc, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import FollowUpTask, Lead, LeadEvent, LeadTag
from app.services.viewer_scope import ViewerIdentity, viewer_lead_filter

# ── Raw SQL constants ──────────────────────────────────────────────

_FETCH_SQL = text(
    """
    SELECT id, zalo_id, contact_id, name, phone, birth_year, age, living_area, address, gender,
           region, desired_job, years_experience, expected_salary, avatar_url,
           lead_score, lead_stage, notes, version
    FROM leads WHERE zalo_id = :zalo_id
    """
)


def _merge_assignments(source: str) -> str:
    """Lead merge expressions shared by both write paths.

    ``source`` qualifies the incoming values: ``EXCLUDED.`` inside an
    ``ON CONFLICT`` clause, ``:`` (a bind name) inside a plain UPDATE. One
    template so the INSERT-on-conflict merge and the contact-keyed merge
    cannot drift.
    """
    return f"""
        name = COALESCE(NULLIF({source}name,''), leads.name),
        phone = COALESCE(NULLIF({source}phone,''), leads.phone),
        birth_year = COALESCE({source}birth_year, leads.birth_year),
        age = COALESCE({source}age, leads.age),
        living_area = COALESCE(NULLIF({source}living_area,''), leads.living_area),
        address = COALESCE(NULLIF({source}address,''), leads.address),
        gender = COALESCE(NULLIF({source}gender,''), leads.gender),
        region = COALESCE(NULLIF({source}region,''), leads.region),
        desired_job = COALESCE(NULLIF({source}desired_job,''), leads.desired_job),
        years_experience = COALESCE(NULLIF({source}years_experience,''), leads.years_experience),
        expected_salary = COALESCE(NULLIF({source}expected_salary,''), leads.expected_salary),
        lead_score = COALESCE(CAST({source}lead_score AS lead_score), leads.lead_score),
        notes = CASE
            WHEN CAST({source}notes AS text) IS NULL
                 OR CAST({source}notes AS text) = '' THEN leads.notes
            WHEN leads.notes IS NULL OR leads.notes = ''
                 THEN CAST({source}notes AS text)
            ELSE concat_ws(
                E'\\n',
                leads.notes,
                (
                    SELECT string_agg(incoming.note, E'\\n' ORDER BY incoming.line_order)
                    FROM (
                        SELECT btrim(split.line) AS note, split.line_order
                        FROM regexp_split_to_table(CAST({source}notes AS text), chr(10))
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
                                  regexp_replace(btrim(incoming.note), '[[:space:]]+', ' ', 'g'),
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
    """


_UPSQL = text(
    f"""
    INSERT INTO leads (zalo_id, name, phone, birth_year, age, living_area, address, gender,
        region, desired_job, years_experience, expected_salary, lead_score,
        notes, version)
    VALUES (:zalo_id, :name, :phone, :birth_year, :age, :living_area, :address, :gender,
        :region, :desired_job, :years_experience, :expected_salary, :lead_score,
        :notes, 1)
    ON CONFLICT (zalo_id) DO UPDATE SET{_merge_assignments("EXCLUDED.")}
    RETURNING id
    """
)

# Messenger rows are keyed by ``contact_id`` with a NULL ``zalo_id`` (migration
# 0047), so a chat-id lookup never finds them. The latest lead for the contact
# wins — multiple leads may share a contact, and the stub trigger only dedups
# NEW-stage rows.
_BY_CONTACT_SQL = text(
    """
    SELECT id, zalo_id, contact_id, name, phone, birth_year, age, living_area, address, gender,
           region, desired_job, years_experience, expected_salary, avatar_url,
           lead_score, lead_stage, notes, version
    FROM leads WHERE contact_id = CAST(:contact_id AS uuid)
    ORDER BY updated_at DESC, id DESC
    LIMIT 1
    """
)

# Contact-keyed merge: the row is located by contact_id, so its NULL zalo_id
# is preserved and leads_zalo_id_fkey is never exercised. The latest lead for
# the contact wins, matching _BY_CONTACT_SQL.
_UPDATE_BY_CONTACT_SQL = text(
    f"""
    WITH target AS (
        SELECT id FROM leads
        WHERE contact_id = CAST(:contact_id AS uuid)
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        FOR UPDATE
    )
    UPDATE leads SET{_merge_assignments(":")}
    WHERE id IN (SELECT id FROM target)
    RETURNING id
    """
)

# Fallback for a contact that has no lead row yet. zalo_id is a literal NULL —
# that is the point of the contact-keyed write, and it keeps the
# leads_zalo_id_fkey intact. lead_stage falls through to the column default,
# exactly as _UPSQL already does.
_INSERT_BY_CONTACT_SQL = text(
    """
    INSERT INTO leads (contact_id, zalo_id, name, phone, birth_year, age, living_area,
        address, gender, region, desired_job, years_experience, expected_salary,
        lead_score, notes, version)
    VALUES (CAST(:contact_id AS uuid), NULL, :name, :phone, :birth_year, :age,
        :living_area, :address, :gender, :region, :desired_job, :years_experience,
        :expected_salary, CAST(:lead_score AS lead_score), :notes, 1)
    RETURNING id
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

    async def upsert_by_contact(self, contact_id: str, lead: dict) -> int | None:
        """Insert or merge a normalised lead by ``contact_id``; return the lead id.

        Messenger rows are contact-keyed, so the zalo_id-keyed upsert would
        violate ``leads_zalo_id_fkey``. The advisory lock closes the insert race:
        two jobs for a contact with no lead yet would otherwise both miss the
        UPDATE and both insert.
        """
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:contact_id, 0))"),
            {"contact_id": str(contact_id)},
        )
        params = {**lead, "contact_id": str(contact_id)}
        lead_id = (await self.db.execute(_UPDATE_BY_CONTACT_SQL, params)).scalar()
        if lead_id is None:
            lead_id = (await self.db.execute(_INSERT_BY_CONTACT_SQL, params)).scalar()
        await self.db.flush()
        return lead_id

    async def by_zalo_id(self, zalo_id: str) -> dict | None:
        """Fetch an existing lead by ``zalo_id``; return all columns as a dict, or None."""
        row = await self.db.execute(_FETCH_SQL, {"zalo_id": zalo_id})
        result = row.mappings().first()
        return dict(result) if result else None

    async def get_visible(self, lead_id: int, *, viewer: ViewerIdentity) -> Lead | None:
        """Fetch one lead the ``viewer`` is allowed to see; None when out of scope.

        Mirrors :func:`app.services.viewer_scope.viewer_can_access_lead`: admins
        get the row, recruiters only their own or unassigned rows. Callers map
        ``None`` to a 404 so the sequential id space is not probeable.
        """
        stmt = viewer_lead_filter(select(Lead).where(Lead.id == lead_id), viewer)
        return (await self.db.scalars(stmt)).first()

    async def set_gender_by_id(self, lead_id: int, gender: str, *, override: bool = False) -> bool:
        """Write a gender onto a lead by primary key; True when a row changed.

        The blank-only guarantee is part of the statement — ``gender IS NULL OR
        btrim(gender) = ''`` — so a value a provider or a recruiter wrote
        between the caller's read and this write is never replaced. There is no
        read-then-write window to lose.

        ``override`` is the candidate explicitly self-referring in the current
        message; the candidate's own word outranks an earlier inference, so that
        case overwrites and advances ``version`` (a real edit the recruiter
        console must reconcile). ``updated_at`` always moves so the write is
        visible; a blank fill leaves ``version`` alone.
        """
        values: dict = {"gender": gender, "updated_at": func.now()}
        if override:
            values["version"] = Lead.version + 1
        stmt = update(Lead).where(Lead.id == lead_id).values(**values)
        if not override:
            stmt = stmt.where(or_(Lead.gender.is_(None), func.btrim(Lead.gender) == ""))
        result = await self.db.execute(stmt.execution_options(synchronize_session=False))
        return result.rowcount > 0

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
