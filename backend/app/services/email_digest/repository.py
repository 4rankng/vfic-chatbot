"""Windowed candidate collection for the candidate email digest.

One digest run issues only batched queries (leads, identities, channel
accounts, Page↔Project mappings, conversations, projects, messages) — never a
per-candidate query loop, which would trip the repo's static I/O-in-loop
findings. Channel labels reuse ``channel_accounts.label`` when the operator
named the account (e.g. "VietPhap OA"), falling back to a code map.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel_account import ChannelAccount, ChannelAccountProject
from app.models.company import Project
from app.models.contact import ContactChannelIdentity
from app.models.conversation import Conversation, Message, MessageSender
from app.models.lead import Lead
from app.services.viewer_scope import support_leads_condition

# Bounded email: a long outage must not turn one digest into a 500-row letter.
MAX_CANDIDATES_PER_DIGEST = 50
# Last-N candidate messages fed to the summarizer per candidate.
MESSAGES_PER_CANDIDATE = 12

PROVIDER_ZALO_BOT = "zalo_bot"
PROVIDER_ZALO_OA = "zalo_oa"
PROVIDER_FACEBOOK_MESSENGER = "facebook_messenger"

_FALLBACK_CHANNEL_LABELS = {
    PROVIDER_ZALO_BOT: "Zalo Chatbot",
    PROVIDER_ZALO_OA: "Zalo OA",
    PROVIDER_FACEBOOK_MESSENGER: "Messenger",
}


@dataclass
class DigestCandidate:
    """Row DTO for one digest entry. Mutable: the service fills ``summary``."""
    lead_id: int
    name: str | None = None
    phone: str | None = None
    age: int | None = None
    gender: str | None = None
    living_area: str | None = None
    address: str | None = None
    desired_job: str | None = None
    years_experience: str | None = None
    expected_salary: str | None = None
    channel_label: str = ""
    project_name: str | None = None
    # Every project the candidate's channel account maps to, sorted. Kept whole
    # so the summarizer may narrow an ambiguous mapping to one project without
    # the digest inventing a factory the channel never claimed.
    mapped_projects: tuple[str, ...] = ()
    # Which campaign/ad brought the candidate in, as recorded on the
    # conversation's first touch: the Messenger ad's title, the operator's
    # ``ref`` code, or the raw Meta ad id. None when the entry carried no
    # source. This is the recruiter's "which ad did this lead click" answer.
    campaign: str | None = None
    candidate_messages: tuple[str, ...] = ()
    summary: str | None = None


# The seeded default OA label (Alembic 0047) reads like a product name in a
# customer-facing file; the digest always shows the short brand form.
_LABEL_CANONICALIZATION = {"Zalo Official Account": "Zalo OA"}


def channel_label(provider: str, account_key: str, account_label: str | None) -> str:
    """Display label for one contact identity; the operator's account label wins."""
    if provider == PROVIDER_ZALO_OA and account_label:
        label: str = account_label
    else:
        label = _FALLBACK_CHANNEL_LABELS.get(provider, provider)
    return _LABEL_CANONICALIZATION.get(label, label)


def _attribution_project_id(attribution: object) -> object:
    """The project a conversation's campaign resolved to, if any.

    ``conversations.attribution`` is the candidate's first-touch source, and
    ``ingress`` already resolves its ``ref`` / ``ad_title`` to a project
    (see ``services/lead/interest.py``). It arrives as a UUID string, so it is
    normalised here rather than trusted into the Project lookup as-is.
    """
    if not isinstance(attribution, dict):
        return None
    raw = attribution.get("project_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _campaign_label(attribution: object) -> str | None:
    """A recruiter-readable name for the campaign a candidate entered from.

    ``conversations.attribution`` carries several keys because Meta sends
    several: the ad's creative ``ad_title`` reads best, then the operator's own
    ``ref`` code, then the raw Meta ``ad_id``. ``project_id`` is derived, not a
    campaign name, and never shown here. None when the entry had no source —
    an organic or QR-code conversation honestly says nothing about an ad.
    """
    if not isinstance(attribution, dict):
        return None
    for key in ("ad_title", "post_code", "ad_id"):
        value = attribution.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _project_of_interest(
    focused_id: object,
    project_names: dict,
    mapped_names: list[str],
    attributed_id: object = None,
) -> str | None:
    """Project of interest for one candidate, in descending strength.

    The bot-confirmed focus wins; then the project the candidate's CAMPAIGN
    resolved to (an operator-typed ``ref`` or an ad creative title matched
    against the catalog) — the system had already resolved that from the thread
    before the candidate typed a word, so it says more about why this person is
    here than the Page they happened to message; a Page mapped to exactly one
    project implies it (the LG Display fanpage case); with SEVERAL mappings the
    column lists every candidate the channel could mean rather than staying
    blank — an ambiguous channel is real information the recruiter can act on,
    and a blank cell hid all of it. The list is the honest fallback; the
    summarizer may then narrow it to one project, but only to a name that is
    already in this set.
    """
    if focused_id is not None:
        return project_names.get(focused_id)
    if attributed_id is not None and attributed_id in project_names:
        return project_names[attributed_id]
    if not mapped_names:
        return None
    return ", ".join(sorted(mapped_names))


async def collect_new_candidates(
    db: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[DigestCandidate]:
    """Leads whose candidate messaged the bot inside the window, phone required.

    Inclusion (operator rule 2026-10-06) has exactly two conditions: the
    candidate's LATEST message to the bot falls inside the window, and the
    lead carries a mobile number. The window therefore tracks CONVERSATION
    ACTIVITY rather than ``Lead.created_at`` — a candidate who first touched
    days ago but messaged yesterday is in, while a lead stubbed yesterday that
    never typed is out. Keying on lead creation was what emptied the digest:
    the conversation trigger creates a lead per conversation immediately, so
    "created in the window" said nothing about whether anyone actually talked.

    Phone is a hard filter in the query: the Excel is the payload and the
    service drops phoneless rows anyway, so a busy window (the Messenger stub
    trigger) must never let phoneless rows consume the
    ``MAX_CANDIDATES_PER_DIGEST`` slice.

    The exclusion is the established ``support_leads_condition()`` predicate —
    the employee-support OA account ("tingting") is never a recruitment
    candidate, so its leads never reach the digest regardless of what other
    channels the operator runs.
    """
    _has_phone = func.btrim(func.coalesce(Lead.phone, "")) != ""
    # The candidate's latest message per contact — the timestamp that decides
    # window membership. Computed over the whole history, then bounded, so a
    # contact who messaged inside the window AND later (only possible when a
    # caller passes a window_end in the past) is judged on their newest word.
    latest_candidate_message = (
        select(
            Conversation.contact_id.label("contact_id"),
            func.max(Message.created_at).label("last_message_at"),
        )
        .join(Message, Message.conversation_id == Conversation.id)
        .where(Message.sender == MessageSender.WORKER)
        .group_by(Conversation.contact_id)
        .subquery()
    )
    lead_rows = (
        (
            await db.scalars(
                select(Lead)
                .join(
                    latest_candidate_message,
                    latest_candidate_message.c.contact_id == Lead.contact_id,
                )
                .where(
                    latest_candidate_message.c.last_message_at >= window_start,
                    latest_candidate_message.c.last_message_at < window_end,
                )
                .where(_has_phone)
                .where(support_leads_condition())
                .order_by(latest_candidate_message.c.last_message_at.asc())
                .limit(MAX_CANDIDATES_PER_DIGEST)
            )
        )
        .all()
    )
    if not lead_rows:
        return []

    contact_ids = [lead.contact_id for lead in lead_rows if lead.contact_id is not None]

    # ── Identities + operator account labels (channel display names) ────────
    identity_by_contact: dict = {}
    account_labels: dict[tuple[str, str], str] = {}
    account_id_by_pair: dict[tuple[str, str], object] = {}
    if contact_ids:
        ident_rows = (
            await db.execute(
                select(ContactChannelIdentity)
                .where(ContactChannelIdentity.contact_id.in_(contact_ids))
                .order_by(ContactChannelIdentity.created_at.asc())
            )
        ).scalars().all()
        for ident in ident_rows:
            # Earliest identity = the contact's primary channel.
            identity_by_contact.setdefault(ident.contact_id, ident)
        pairs = {
            (ident.provider, ident.account_key) for ident in ident_rows
        }
        if pairs:
            account_rows = (
                await db.execute(
                    select(ChannelAccount).where(
                        and_(
                            ChannelAccount.provider.in_({pair[0] for pair in pairs}),
                            ChannelAccount.account_key.in_({pair[1] for pair in pairs}),
                        )
                    )
                )
            ).scalars().all()
            account_labels = {
                (row.provider, row.account_key): row.label for row in account_rows
            }
            account_id_by_pair = {
                (row.provider, row.account_key): row.id for row in account_rows
            }

    # ── Page↔Project mapping → the fallback project of interest ────────────
    # A fanpage mapped to exactly one project (e.g. the LG Display page)
    # implies that project for leads arriving through it — most candidates ask
    # one-off questions and the bot never confirms a focused project. The
    # bot-confirmed focus still wins; with several mapped projects nothing is
    # guessed.
    mapped_projects_by_pair: dict[tuple[str, str], set] = {}
    if account_id_by_pair:
        pair_by_account_id = {v: k for k, v in account_id_by_pair.items()}
        mapping_rows = (
            await db.scalars(
                select(ChannelAccountProject).where(
                    ChannelAccountProject.channel_account_id.in_(set(pair_by_account_id))
                )
            )
        ).all()
        for row in mapping_rows:
            pair = pair_by_account_id.get(row.channel_account_id)
            if pair is not None:
                mapped_projects_by_pair.setdefault(pair, set()).add(row.project_id)

    # ── Latest conversation per contact → project of interest ──────────────
    conversation_rows: list = []
    if contact_ids:
        conversation_rows = (
            (
                await db.scalars(
                    select(Conversation)
                    .where(Conversation.contact_id.in_(contact_ids))
                    .order_by(Conversation.created_at.desc())
                )
            )
            .all()
        )
    latest_conversation: dict = {}
    for conv in conversation_rows:
        latest_conversation.setdefault(conv.contact_id, conv)

    project_ids = {
        conv.focused_project_id
        for conv in latest_conversation.values()
        if conv.focused_project_id is not None
    }
    # A campaign-resolved project must be loadable too, or the column would
    # silently fall back to the channel mapping for exactly the ad-sourced
    # leads the recruiter most wants to attribute.
    for conv in latest_conversation.values():
        attributed_id = _attribution_project_id(getattr(conv, "attribution", None))
        if attributed_id is not None:
            project_ids.add(attributed_id)
    for project_set in mapped_projects_by_pair.values():
        project_ids.update(project_set)
    project_names: dict = {}
    if project_ids:
        project_rows = (
            await db.scalars(select(Project).where(Project.id.in_(project_ids)))
        ).all()
        project_names = {row.id: row.name for row in project_rows}

    # ── Candidate-side messages for the summarizer ──────────────────────────
    messages_by_conversation: dict = {}
    conversation_ids = [conv.id for conv in latest_conversation.values()]
    if conversation_ids:
        message_rows = (
            (
                await db.scalars(
                    select(Message)
                    .where(Message.conversation_id.in_(conversation_ids))
                    .where(Message.sender == MessageSender.WORKER)
                    .order_by(Message.created_at.asc())
                )
            )
            .all()
        )
        for message in message_rows:
            messages_by_conversation.setdefault(message.conversation_id, []).append(
                message.body
            )

    candidates: list[DigestCandidate] = []
    # The query already capped the slice and ordered it by each candidate's
    # latest message, so presentation follows conversation activity.
    selected = lead_rows
    for lead in selected:
        ident = identity_by_contact.get(lead.contact_id)
        conv = latest_conversation.get(lead.contact_id)
        messages = messages_by_conversation.get(conv.id, []) if conv is not None else []
        pair = (ident.provider, ident.account_key) if ident is not None else None
        focused_id = conv.focused_project_id if conv is not None else None
        attribution = getattr(conv, "attribution", None) if conv is not None else None
        attributed_id = _attribution_project_id(attribution)
        mapped_names = sorted(
            project_names[pid]
            for pid in mapped_projects_by_pair.get(pair, set())
            if pid in project_names
        )
        project_name = _project_of_interest(
            focused_id, project_names, mapped_names, attributed_id
        )
        candidates.append(
            DigestCandidate(
                lead_id=lead.id,
                name=lead.name,
                phone=lead.phone,
                age=lead.age,
                gender=lead.gender,
                living_area=lead.living_area,
                address=lead.address,
                desired_job=lead.desired_job,
                years_experience=lead.years_experience,
                expected_salary=lead.expected_salary,
                channel_label=(
                    channel_label(
                        ident.provider,
                        ident.account_key,
                        account_labels.get((ident.provider, ident.account_key)),
                    )
                    if ident is not None
                    else ""
                ),
                project_name=project_name,
                mapped_projects=tuple(mapped_names),
                campaign=_campaign_label(attribution),
                candidate_messages=tuple(messages[-MESSAGES_PER_CANDIDATE:]),
            )
        )
    return candidates
