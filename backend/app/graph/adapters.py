"""Port adapters owned by the graph composition root.

``_DirectContextAdapter`` (focused-project routing + direct-context KB lane),
``_FaqBypassAdapter`` (deterministic FAQ cascade), and ``_RuntimePolicyAdapter``
(installation-backed policy stamps) implement the Protocols from
``graph/ports.py``. They are split out of ``factories.py`` so each composition
module holds one concern; concrete ``app.models`` / ``app.services`` imports stay
function-level here, which is exactly what the graph import guard checks for
composition modules.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.recruitment.domain.recommendation import (
    is_salary_profile_statement,
    parse_salary_band,
)

logger = logging.getLogger(__name__)


def _asks_to_explore(normalized_message: str) -> bool:
    return any(
        phrase in normalized_message
        for phrase in (
            "du an khac",
            "cong ty khac",
            "nha may khac",
            "viec khac",
            "xem tat ca",
            "tat ca du an",
            "quay lai tim viec",
        )
    )


def _is_general_or_comparative(normalized_message: str) -> bool:
    """True when a question is factory-agnostic and comparative/general.

    Such questions must NOT be answered from one (focused) project's KB: a salary
    threshold hypothetical ("lam 20 trieu duoc ko"), a superlative ("luong cao
    nhat"), or an explicit multi-factory scope ("nha may nao", "bao nhieu nha
    may"). A bare "luong bao nhieu" is a focused follow-up and returns False, so
    an established focus is preserved for ordinary project-scoped questions.
    """
    text = normalized_message or ""
    if any(
        phrase in text
        for phrase in (
            # Comparative / superlative (inherently cross-project).
            "cao nhat",
            "thap nhat",
            "nhieu nhat",
            "it nhat",
            "tot nhat",
            "gan nhat",
            "moi nhat",
            "xa nhat",
            "so sanh",
            # Explicit multi-factory scope / "which job" browsing.
            "nha may nao",
            "bao nhieu nha may",
            "co bao nhieu nha may",
            "viec lam nao",
            "viec nao",
            "du an nao",
            "cac nha may",
            "cac du an",
            "tat ca nha may",
        )
    ):
        return True
    if is_salary_profile_statement(text):
        return False
    _minimum, target = parse_salary_band(text)
    if target is None:
        return False
    if "luong" in text or "thu nhap" in text:
        return True
    tokens = set(text.split())
    return "lam" in tokens and bool(tokens & {"duoc", "dc"})


@dataclass(frozen=True)
class _DirectContextCatalogEntry:
    """One active project as the direct-context lane needs it for routing.

    Plain data on purpose: the catalog is served from the Redis preamble cache
    on cache hits, where no ORM entity exists. ``project_id``/``kb_id`` keep the
    row's native type (UUID in production) so focused-id comparisons and
    conversation writes stay exact; they are only stringified for the cache
    payload.
    """

    project_id: uuid.UUID | str
    slug: str
    name: str
    aliases: tuple[str, ...]
    kb_id: uuid.UUID | str
    mode: str  # KnowledgeBaseMode value


# The TTL is a safety net for a missed version bump (mirrors the preamble
# system-prompt TTL), not the invalidation mechanism: slug/name/aliases change
# only via admin project edits that already bump ``NS_PREAMBLE``.
_DIRECT_CONTEXT_CATALOG_TTL_SECONDS = 600


def _catalog_entry_from_cache(item: Any) -> _DirectContextCatalogEntry:
    return _DirectContextCatalogEntry(
        project_id=uuid.UUID(item["project_id"]),
        slug=item["slug"],
        name=item["name"],
        aliases=tuple(item["aliases"] or ()),
        kb_id=uuid.UUID(item["kb_id"]),
        mode=item["mode"],
    )


async def _load_direct_context_catalog(db):
    """Active-project routing catalog for the direct-context lane.

    Cached in Redis under the existing ``NS_PREAMBLE`` namespace: the projection
    (slug, name, aliases, KB mode) changes only on admin edits that already bump
    that version (project create/update/delete, KB attach at project create),
    so the versioned key makes the bump the invalidation. The TTL only bounds a
    missed bump — e.g. ``bootstrap_legacy`` attaches a legacy RAG project
    without a bump, so such a project may lag up to 10 minutes behind.

    Best-effort like every cache in ``core.cache``: on any Redis failure the DB
    query runs and no cache entry is written.
    """
    from app.core.cache import cache_get_json, cache_set_json, cache_version
    from app.core.preamble_cache import NS_PREAMBLE
    from sqlalchemy import select

    from app.models.company import Project
    from app.models.knowledge import KnowledgeBase

    version = await cache_version(NS_PREAMBLE)
    key = f"preamble:direct_context_catalog:v{version}"
    cached = await cache_get_json(key)
    if isinstance(cached, list):
        try:
            return [_catalog_entry_from_cache(item) for item in cached]
        except (KeyError, TypeError, ValueError):
            pass  # corrupted payload — fall through to the DB and re-cache
    rows = (
        await db.execute(
            select(Project, KnowledgeBase)
            .join(KnowledgeBase, Project.knowledge_base_id == KnowledgeBase.id)
            .where(Project.is_active.is_(True))
            .order_by(Project.name, Project.id)
        )
    ).all()
    entries = [
        _DirectContextCatalogEntry(
            project_id=project.id,
            slug=project.slug,
            name=project.name,
            aliases=tuple(project.aliases or ()),
            kb_id=knowledge_base.id,
            mode=getattr(knowledge_base.mode, "value", knowledge_base.mode),
        )
        for project, knowledge_base in rows
    ]
    await cache_set_json(
        key,
        [
            {
                "project_id": str(entry.project_id),
                "slug": entry.slug,
                "name": entry.name,
                "aliases": list(entry.aliases),
                "kb_id": str(entry.kb_id),
                "mode": entry.mode,
            }
            for entry in entries
        ],
        ttl_seconds=_DIRECT_CONTEXT_CATALOG_TTL_SECONDS,
    )
    return entries


class _DirectContextAdapter:
    """Route the turn to one active project's knowledge base.

    The routing catalog (slug/name/aliases/mode per active project) is served
    from the Redis preamble cache when unchanged; only the SELECTED project's
    direct-context text is fetched, and only when that KB is in DIRECT_CONTEXT
    mode, via a targeted ``load_only(normalized_text)`` query. The capacity
    guard runs on the pre-fetched file, so a turn never loads the full TEXT
    columns of every active project and never re-SELECTs the file row.
    """

    def __init__(self, db) -> None:
        self._db = db

    async def resolve(self, conversation, user_text: str):
        import re

        from sqlalchemy import select
        from sqlalchemy.orm import load_only

        from app.shared.domain.text import normalize_vietnamese_text
        from app.graph.direct_context import DirectContext, ProjectTurnContext
        from app.recruitment.domain.provider import provider_from_conversation
        from app.graph.prompts import AGENT_SYSTEM_PROMPT
        from app.models.knowledge import KnowledgeBaseDirectFile, KnowledgeBaseMode
        from app.models.conversation import ConversationProjectState
        from app.services.knowledge_base_capacity import ensure_direct_context_fits
        from app.services.personas.repository import PersonaRepository

        normalized_message = normalize_vietnamese_text(user_text)
        entries = await _load_direct_context_catalog(self._db)
        matches = []
        for entry in entries:
            names = [entry.slug, entry.name, *(entry.aliases or ())]
            if any(
                re.search(
                    rf"(?<!\w){re.escape(normalize_vietnamese_text(name))}(?!\w)",
                    normalized_message,
                )
                for name in names
                if len(normalize_vietnamese_text(name)) >= 2
            ):
                matches.append(entry)
        if len(matches) > 1:
            names = ", ".join(entry.name for entry in matches)
            return ProjectTurnContext(
                state="EXPLORE",
                clarification=f"Bạn đang muốn hỏi dự án nào: {names}?",
            )

        selected = matches[0] if matches else None
        focused_id = getattr(conversation, "focused_project_id", None)
        if selected is None and _asks_to_explore(normalized_message):
            conversation.project_context_state = ConversationProjectState.EXPLORE
            conversation.focused_project_id = None
            await self._db.commit()
            return ProjectTurnContext(state="EXPLORE")
        if (
            selected is None
            and _is_general_or_comparative(normalized_message)
            and len(entries) >= 2
        ):
            # Factory-agnostic comparative/general question (e.g. a salary
            # threshold "lam 20 trieu duoc ko", "luong cao nhat", "nha may nao").
            # Must NOT be silently answered from one focused project's KB: that
            # is how the bot gave LG Display's "can't confirm 20M" as a universal
            # answer while another factory's KB said 20M is reachable. Keep
            # focused_project_id intact (the user may still be on that thread)
            # but do not pin this turn, so the agent can answer across active
            # projects and ask which one the candidate means.
            return ProjectTurnContext(state="EXPLORE")
        if selected is None and focused_id is not None:
            selected = next(
                (entry for entry in entries if entry.project_id == focused_id), None
            )
        if selected is None:
            if focused_id is not None or getattr(
                conversation, "project_context_state", "EXPLORE"
            ) != ConversationProjectState.EXPLORE:
                conversation.project_context_state = ConversationProjectState.EXPLORE
                conversation.focused_project_id = None
                await self._db.commit()
            return ProjectTurnContext(state="EXPLORE")

        if focused_id != selected.project_id or getattr(
            conversation, "project_context_state", "EXPLORE"
        ) != ConversationProjectState.FOCUSED:
            conversation.project_context_state = ConversationProjectState.FOCUSED
            conversation.focused_project_id = selected.project_id
            await self._db.commit()

        direct_context = None
        if selected.mode == KnowledgeBaseMode.DIRECT_CONTEXT.value:
            provider = provider_from_conversation(conversation)
            persona_body = (
                await PersonaRepository(self._db).active_persona_body(provider)
            ) or AGENT_SYSTEM_PROMPT
            direct_file = await self._db.scalar(
                select(KnowledgeBaseDirectFile)
                .options(load_only(KnowledgeBaseDirectFile.normalized_text))
                .where(KnowledgeBaseDirectFile.knowledge_base_id == selected.kb_id)
            )
            if direct_file is None:
                direct_context = DirectContext(
                    knowledge_base_id=str(selected.kb_id),
                    persona_body=persona_body,
                    knowledge_text="",
                )
            else:
                await ensure_direct_context_fits(
                    self._db, direct_file, agent_markdown=persona_body
                )
                direct_context = DirectContext(
                    knowledge_base_id=str(selected.kb_id),
                    persona_body=persona_body,
                    knowledge_text=direct_file.normalized_text,
                )
        return ProjectTurnContext(
            state="FOCUSED",
            project_id=str(selected.project_id),
            project_slug=selected.slug,
            project_name=selected.name,
            knowledge_mode=selected.mode,
            direct_context=direct_context,
        )


class _FaqBypassAdapter:
    """FaqBypassPort backed by RetrievalRepository + the shared cached embedder.

    Defined in the composition root so the graph layer imports no concrete
    service module (all ``app.services`` imports are function-level, satisfying
    the AST import-guard). Runs the deterministic cascade from
    :mod:`app.services.retrieval.faq_bypass` and logs every decision so the
    thresholds can be tuned from production logs. Never raises — any failure
    abstains so the turn falls through to the agent unchanged.
    """

    def __init__(self, db, embedder, *, page_project_ids=None) -> None:
        self._db = db
        self._embedder = embedder
        self._page_project_ids = page_project_ids

    async def try_answer(self, user_text: str):
        from app.core.vector import vec_literal
        from app.graph.ports import FaqBypassResult
        from app.graph.tools import _cached_embed
        from app.services.retrieval import RetrievalRepository
        from app.services.retrieval import faq_bypass as fb

        started = time.perf_counter()
        repo = RetrievalRepository(self._db, page_project_ids=self._page_project_ids)
        try:
            active_project_ids = getattr(repo, "active_project_ids", None)
            project_ids = await active_project_ids() if active_project_ids is not None else None
            if project_ids == []:
                return None
            emb = vec_literal(await _cached_embed(self._embedder, user_text))
            # Scope follows active_project_ids: the deployment-wide catalog for
            # Zalo, or the Page's assigned Projects when the turn arrived on a
            # scoped Facebook Page. Both arms must carry it — an unscoped FAQ
            # arm answers from another Page's catalog before retrieval runs.
            faq_scope = {"project_ids": project_ids} if project_ids is not None else {}
            vector_rows = await repo.match_faq(
                emb, top_k=fb.TOP_K, floor=fb.CANDIDATE_VECTOR_FLOOR, **faq_scope
            )
            lexical_rows = await repo.match_faq_lexical(
                user_text, top_k=fb.TOP_K, threshold=fb.TRIGRAM_THRESHOLD, **faq_scope
            )
        except Exception:  # noqa: BLE001 — bypass must never break a turn
            logger.warning("faq_bypass retrieval failed; abstaining", exc_info=True)
            return None

        candidates = list(vector_rows) + list(lexical_rows)
        exact_map = fb.build_exact_map(candidates)
        scored = fb.rerank(list(vector_rows), list(lexical_rows))
        decision = fb.decide(user_text, exact_map, scored)
        latency_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "faq_bypass decision=%s tier=%s score=%.3f top2=%.3f margin=%.3f "
            "vec=%.3f tri=%.3f reason=%s latency_ms=%.1f faq_id=%s",
            decision.decision,
            decision.tier,
            decision.top1_score,
            decision.top2_score,
            decision.margin,
            decision.scored.vec_sim if decision.scored else 0.0,
            decision.scored.tri_sim if decision.scored else 0.0,
            decision.reason,
            latency_ms,
            decision.scored.faq_id if decision.scored else None,
        )
        if decision.decision == fb.DECISION_ACCEPT and decision.scored and decision.scored.answer:
            return FaqBypassResult(
                answer=decision.scored.answer,
                faq_id=decision.scored.faq_id,
                tier=decision.tier,
                score=decision.top1_score,
                reason=decision.reason,
                latency_ms=latency_ms,
                runner_up_score=decision.top2_score if decision.top2_score > 0 else None,
            )
        return None


class _RuntimePolicyAdapter:
    """Installation-backed policy adapter owned by the graph composition root."""

    def __init__(self, db) -> None:
        self._db = db

    async def resolve_active_policy(self):
        from app.graph.runtime_policy import build_resolved_runtime_policy
        from app.shared.domain.errors import InstallationError
        from app.services.installation.service import InstallationService

        installation = InstallationService(self._db)
        try:
            active = await installation.require_active()
        except InstallationError:
            return None
        persona = await installation.repo.get_persona_version(active.revision.persona_version_id)
        return build_resolved_runtime_policy(
            active,
            persona_body=persona.body_md if persona is not None else None,
        )

    async def runtime_stamp_is_current(
        self, *, revision_id: str, authority_generation: int, runtime_fingerprint: str
    ) -> bool:
        from app.services.installation.authority import RuntimeAuthorityStamp
        from app.services.installation.service import InstallationService

        try:
            return await InstallationService(self._db).runtime_stamp_is_current(
                RuntimeAuthorityStamp(
                    revision_id=uuid.UUID(revision_id),
                    authority_generation=authority_generation,
                    fingerprint=runtime_fingerprint,
                )
            )
        except (ValueError, TypeError):
            return False
