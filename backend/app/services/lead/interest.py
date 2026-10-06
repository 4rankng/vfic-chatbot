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
import re
import uuid

from sqlalchemy import select

from app.models.company import Project
from app.models.lead import LeadEvent
from app.recruitment.domain.provider import lead_key_for_conversation
from app.services.lead.repository import LeadRepository
from app.shared.domain.text import normalize_vietnamese_text

logger = logging.getLogger(__name__)

PROJECT_INTEREST_EVENT = "project_interest"

# How the interest was observed. ``post_link`` = the campaign link/ad the
# candidate entered from (its code resolved to a project); ``chat_focus`` =
# the project resolver pinned a turn to that project. Both are kept in the
# payload so the two signals can coexist instead of overwriting each other.
SOURCE_CHAT_FOCUS = "chat_focus"
SOURCE_POST_LINK = "post_link"


async def _project_catalog(db) -> list[tuple[str, str, str, list[str]]]:
    """``(id, slug, name, aliases)`` for every catalog row, active first.

    One loader behind both resolvers so "which project is this ad" has a single
    definition. Ordering keeps the historical tie-break (active rows beat
    archived ones, then slug) that :func:`resolve_project_by_code` relies on.
    Never raises — a catalog problem degrades to "no match", because both
    callers sit on the inbound path.
    """
    try:
        rows = (
            await db.execute(
                select(Project.id, Project.slug, Project.name, Project.aliases).order_by(
                    Project.is_active.desc(), Project.slug.asc()
                )
            )
        ).all()
        return [
            (str(pid), str(slug or ""), str(name or ""), list(aliases or []))
            for pid, slug, name, aliases in rows
        ]
    except Exception:  # noqa: BLE001 — a hint resolver never fails an inbound
        logger.warning("project catalog load failed", exc_info=True)
        return []


async def resolve_project_by_code(db, code: str | None) -> str | None:
    """Project id a campaign code points at, or ``None``.

    The code is the ``ref`` a campaign link carries (Messenger ``m.me`` /
    ad destination; a Zalo prefill code later) and it matches a project by
    **case-insensitive ``slug``** or by any entry of ``projects.aliases``
    (case-insensitive, trimmed). Never raises: this runs on the inbound path,
    so a catalog problem must degrade to "no project", never to a dropped
    message. Only called when a code is actually present.

    Inactive projects still match: the archived row is the historical record of
    a project we once recruited for, and a live ad for it would otherwise lose
    its attribution silently. The ``ad_title`` matcher below is deliberately
    stricter (active only) — it guesses from free text, which is a different
    risk than reading a code an operator typed deliberately.
    """
    normalized = (code or "").strip().lower()
    if not normalized:
        return None
    for project_id, slug, _name, aliases in await _project_catalog(db):
        if slug.strip().lower() == normalized:
            return project_id
        for alias in aliases:
            if str(alias or "").strip().lower() == normalized:
                return project_id
    return None


def _project_names(slug: str, name: str, aliases: list[str]) -> list[str]:
    """Every string this project may be named by in ad creative copy."""
    return [value for value in (slug, name, *aliases) if value and str(value).strip()]


def _project_named_in(normalized_title: str, slug: str, name: str, aliases: list[str]) -> bool:
    """Whether an ad title mentions this project by any of its names.

    Accent-insensitive and word-anchored, reusing the same rules the in-chat
    project resolver uses (``graph/adapters.py``): a name must appear as a
    whole word, so "Rorze" cannot fire inside "Rorze2", and a name shorter than
    two normalized characters is ignored because it matches almost anything.
    """
    for raw in _project_names(slug, name, aliases):
        normalized_name = normalize_vietnamese_text(str(raw))
        if len(normalized_name) < 2:
            continue
        if re.search(rf"(?<!\w){re.escape(normalized_name)}(?!\w)", normalized_title):
            return True
    return False


async def resolve_project_from_ad_title(db, title: str | None) -> str | None:
    """Project an ad's creative title names, or ``None``.

    The fallback for Click-to-Messenger ads that set no custom ``ref``: Meta
    ships ``ads_context_data.ad_title`` with the referral, and an ad written as
    "Tuyển dụng dự án RORZE — Hải Phòng" already says which dự án it is for.
    Matching is therefore free text, so it is held to a higher bar than the
    ``ref`` path: active projects only, and **an ambiguous title resolves to
    nothing**. Guessing between two dự án would silently attribute a candidate
    to the wrong recruiter queue, which is worse than leaving them unattributed
    — the chat-focus signal can still pin them later.
    """
    normalized_title = normalize_vietnamese_text(str(title or ""))
    if len(normalized_title) < 2:
        return None
    try:
        # Stringified on both sides: this resolver returns ids as ``str`` (every
        # consumer stores them in JSONB attribution), while the id column yields
        # ``UUID``. Comparing the raw objects would silently match nothing.
        active_ids = {
            str(value)
            for value in await db.scalars(
                select(Project.id).where(Project.is_active.is_(True))
            )
        }
    except Exception:  # noqa: BLE001 — a hint resolver never fails an inbound
        logger.warning("ad title project resolution failed", exc_info=True)
        return None
    if not active_ids:
        return None
    matched: str | None = None
    for project_id, slug, name, aliases in await _project_catalog(db):
        if project_id not in active_ids:
            continue
        if _project_named_in(normalized_title, slug, name, aliases):
            if matched is not None and matched != project_id:
                logger.info("ad title names more than one project; attributing neither")
                return None
            matched = project_id
    return matched


async def resolve_project_from_attribution(db, attribution: dict | None) -> str | None:
    """The dự án a referral names, or ``None``.

    The single answer to "which project is this ad for", used by BOTH entry
    paths — the Get Started / m.me postback (before the candidate types) and
    the first inbound message — so an ad cannot resolve to one project on one
    path and another on the other. Cascade:

    1. ``post_code`` (the ad's ``ref``) — exact match against slug/aliases. An
       operator typed it, so it wins outright.
    2. ``ad_title`` — substring match over the catalog, for ads running today
       that set no ref.

    An already-resolved ``project_id`` short-circuits, so re-resolution never
    replaces a first touch with a weaker guess. Never raises: this runs on the
    inbound path, where a catalog problem must degrade to "no project" rather
    than drop a candidate's first message.
    """
    if not attribution:
        return None
    existing = attribution.get("project_id")
    if existing:
        return str(existing)
    code = attribution.get("post_code")
    if code and str(code).strip():
        resolved = await resolve_project_by_code(db, str(code))
        if resolved:
            return resolved
    title = attribution.get("ad_title")
    if title and str(title).strip():
        return await resolve_project_from_ad_title(db, str(title))
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
        # The lead's own dự án column (Alembic 0071), written here — the same
        # seam as the interest events below, so the two artifacts are written
        # together and can never disagree. The FIRST signal wins (link before
        # focus, see _project_signals) and the repository's ``IS NULL`` guard
        # makes that hold across turns and retries.
        await repo.set_project_by_id(int(lead["id"]), str(signals[0][0]))
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
            logger.warning("project interest with non-uuid project_id lead=%s skipped", lead_id)
    projects = {
        str(project.id): project
        for project in (
            await db.scalars(select(Project).where(Project.id.in_(wanted))) if wanted else []
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
