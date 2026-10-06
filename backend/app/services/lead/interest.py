"""Durable project interest: which dự án a candidate is interested in.

Two SIGNALS feed the record:

* ``post_link`` — the project a campaign link/ad resolved to (Messenger ``ref``
  matched against the project catalog at inbound → ``attribution.project_id``);
* ``chat_focus`` — the project the conversation's turn focus points at.

Two SEAMS write them. The conversation trigger (Alembic 0047) creates a lead
row together with the conversation, so both resolve the lead immediately:

* ``conversation/bot_outcome.py`` — after every recorded turn outcome;
* ``candidate_extraction.py`` — a backstop for a turn whose outcome never ran
  (crash / reconcile).

The record is an idempotent ``lead_events`` row (event_type
``project_interest``): one row per (lead, project), carrying whichever source
got there first — the first interest date is the fact worth keeping. No
migration — ``lead_events.payload`` is already JSONB.

Both writers are best-effort with their own commit: interest is a hint and must
never block the outcome row or the extraction job that carry it.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.models.company import Project
from app.models.lead import LeadEvent
from app.recruitment.domain.provider import lead_key_for_conversation
from app.services.lead.repository import LeadRepository

logger = logging.getLogger(__name__)

PROJECT_INTEREST_EVENT = "project_interest"

# How the interest was observed. ``post_link`` = the campaign link/ad the
# candidate entered from (its code resolved to a project); ``chat_focus`` =
# the project resolver pinned a turn to that project. Both are kept in the
# payload so the two signals can coexist instead of overwriting each other.
SOURCE_CHAT_FOCUS = "chat_focus"
SOURCE_POST_LINK = "post_link"


async def resolve_project_by_code(db, code: str | None) -> str | None:
    """Project id a campaign code points at, or ``None``.

    The code is the ``ref`` a campaign link carries (Messenger ``m.me`` /
    ad destination; a Zalo prefill code later) and it matches a project by
    **case-insensitive ``slug``** or by any entry of ``projects.aliases``
    (case-insensitive, trimmed). Never raises: this runs on the inbound path,
    so a catalog problem must degrade to "no project", never to a dropped
    message. Only called when a code is actually present.
    """
    normalized = (code or "").strip().lower()
    if not normalized:
        return None
    try:
        rows = (
            await db.execute(
                select(Project.id, Project.slug, Project.aliases)
                .order_by(Project.is_active.desc(), Project.slug.asc())
            )
        ).all()
        for project_id, slug, aliases in rows:
            if str(slug or "").strip().lower() == normalized:
                return str(project_id)
            for alias in aliases or []:
                if str(alias or "").strip().lower() == normalized:
                    return str(project_id)
        return None
    except Exception:  # noqa: BLE001 — a hint resolver never fails an inbound
        logger.warning("project code resolution failed code=%s", normalized, exc_info=True)
        return None


def _project_signals(conv) -> list[tuple[object, str]]:
    """``(project, source)`` pairs this conversation carries, link first.

    The campaign link/ad comes before the turn focus so a first-touch record
    names the project the candidate came *for*; the focus (often the same
    project) then dedupes against it instead of overwriting it.
    """
    signals: list[tuple[object, str]] = []
    attribution = getattr(conv, "attribution", None) or {}
    link_project = attribution.get("project_id")
    if link_project:
        signals.append((link_project, SOURCE_POST_LINK))
    focus_project = getattr(conv, "focused_project_id", None)
    if focus_project:
        signals.append((focus_project, SOURCE_CHAT_FOCUS))
    return signals


async def record_conversation_project_interest(db, conv) -> bool:
    """Attach every project signal of a conversation to its candidate's lead.

    Signals: the project the campaign link/ad resolved to
    (``attribution.project_id``) and the project the conversation is focused
    on — either can be the only one present (a link entry that never focuses,
    a focus from an organic entry). Idempotent per (lead, project). Commits
    its own transaction and swallows every failure — both callers sit on
    load-bearing paths (the outcome row, the extraction job) where a hint must
    never break the caller. Returns whether a NEW interest was recorded.
    """
    if conv is None or getattr(conv, "id", None) is None:
        return False
    signals = _project_signals(conv)
    if not signals:
        return False
    try:
        key = lead_key_for_conversation(conv)
        repo = LeadRepository(db)
        # Same key resolution as extraction: a Zalo row matches on zalo_id
        # (the leads_zalo_id_fkey it satisfies), a Messenger row on contact.
        if key.zalo_id:
            lead = await repo.by_zalo_id(key.zalo_id)
        elif key.contact_id:
            lead = await repo.by_contact_id(key.contact_id)
        else:
            lead = None
        if lead is None:
            return False
        recorded = False
        for project_id, source in signals:
            if await record_project_interest(
                db,
                lead_id=int(lead["id"]),
                project_id=project_id,
                source=source,
                conversation_id=conv.id,
            ):
                recorded = True
        # Own transaction: the caller may have committed already, and the hint
        # must survive whatever the caller does next.
        await db.commit()
        return recorded
    except Exception:  # noqa: BLE001 — a hint never breaks the turn or extraction
        logger.warning(
            "project interest record failed conversation=%s",
            getattr(conv, "id", None),
            exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001 — rollback failure stays silent too
            logger.debug("project interest rollback failed", exc_info=True)
        return False


async def record_project_interest(
    db,
    *,
    lead_id: int,
    project_id,
    source: str,
    conversation_id=None,
) -> bool:
    """Write one (lead, project) interest event; False when already known.

    Flushes into the caller's transaction — only
    :func:`record_conversation_project_interest` commits, so a direct caller
    owns its own commit.
    """
    project_key = str(project_id)
    existing = await db.scalar(
        select(LeadEvent.id)
        .where(
            LeadEvent.lead_id == lead_id,
            LeadEvent.event_type == PROJECT_INTEREST_EVENT,
            LeadEvent.payload["project_id"].astext == project_key,
        )
        .limit(1)
    )
    if existing is not None:
        return False
    db.add(
        LeadEvent(
            lead_id=lead_id,
            event_type=PROJECT_INTEREST_EVENT,
            payload={
                "project_id": project_key,
                "source": source,
                "conversation_id": str(conversation_id) if conversation_id else None,
            },
        )
    )
    await db.flush()
    return True


async def project_interests(db, lead_id: int) -> list[dict]:
    """Resolved interests for one lead, oldest first.

    The project's current slug/name is read live (a renamed project must not
    report a stale name), so a stored id whose project was deleted simply drops
    out of the list.
    """
    # ScalarResult is iterable directly, which also keeps this callable under
    # the lightweight AsyncMock sessions the API-scope tests inject.
    events = list(
        await db.scalars(
            select(LeadEvent)
            .where(
                LeadEvent.lead_id == lead_id,
                LeadEvent.event_type == PROJECT_INTEREST_EVENT,
            )
            .order_by(LeadEvent.created_at.asc())
        )
    )
    if not events:
        return []
    wanted: list[uuid.UUID] = []
    for event in events:
        raw = str((event.payload or {}).get("project_id") or "")
        try:
            wanted.append(uuid.UUID(raw))
        except ValueError:
            logger.warning(
                "project interest with non-uuid project_id lead=%s skipped", lead_id
            )
    projects = {
        str(project.id): project
        for project in (
            await db.scalars(select(Project).where(Project.id.in_(wanted)))
            if wanted
            else []
        )
    }
    interests: list[dict] = []
    for event in events:
        payload = event.payload or {}
        project_id = str(payload.get("project_id") or "")
        project = projects.get(project_id)
        if project is None:
            continue
        interests.append(
            {
                "project_id": project.id,
                "project_slug": project.slug,
                "project_name": project.name,
                "source": str(payload.get("source") or ""),
                "first_interested_at": event.created_at,
            }
        )
    return interests


__all__ = [
    "PROJECT_INTEREST_EVENT",
    "SOURCE_CHAT_FOCUS",
    "SOURCE_POST_LINK",
    "project_interests",
    "record_conversation_project_interest",
    "record_project_interest",
    "resolve_project_by_code",
]
