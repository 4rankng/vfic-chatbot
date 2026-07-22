"""Dependency factories for the graph's LLM/embedder wiring.

- ``build_deps`` wires the full ``GraphDeps`` for the chatbot worker.
- ``build_minimax_extractor`` — candidate extraction (persistence worker).
- ``make_minimax_llm_json`` — JSON-mode LLM for the knowledge training pipeline (ingest worker).

langchain_openai is imported lazily inside each factory so the web-process import path
stays langchain-free.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.core.config import get_settings
from app.graph.clients import (
    MiniMaxAgent,
    _chat_for_role,
    _minimax_chat,
    _openrouter_chat,
    build_embedder,
)
from app.graph.types import GraphDeps

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


class _LeadContextAdapter:
    """LeadContextPort backed by the concrete lead service pieces.

    Defined here (the composition root) so the graph layer never imports the lead
    service modules. Each method does one DB fetch, matching the prior single-fetch
    behavior of the brain; the caller owns the best-effort try/except.
    """

    def __init__(self, db) -> None:
        self._db = db

    async def profile_text(self, chat_id: str) -> str:
        from app.services.lead import lead_profile_text
        from app.services.lead.repository import LeadRepository

        lead = await LeadRepository(self._db).by_zalo_id(chat_id)
        return lead_profile_text(lead)

    async def context(self, chat_id, current_user_text, recent_messages):
        from app.services.lead import lead_profile_text
        from app.services.lead.probing import lead_collection_question
        from app.services.lead.repository import LeadRepository

        lead = await LeadRepository(self._db).by_zalo_id(chat_id)
        return (
            lead_profile_text(lead),
            lead_collection_question(
                lead=lead,
                current_user_text=current_user_text,
                recent_messages=recent_messages,
            ),
        )

    def instruction(self, question: str) -> str:
        from app.services.lead.probing import lead_collection_instruction

        return lead_collection_instruction(question=question)


class _DirectContextAdapter:
    def __init__(self, db) -> None:
        self._db = db

    async def resolve(self, conversation, user_text: str):
        import re

        from sqlalchemy import select

        from app.core.text import normalize_vietnamese_text
        from app.graph.direct_context import DirectContext, ProjectTurnContext
        from app.graph.provider_scope import provider_from_conversation
        from app.graph.prompts import AGENT_SYSTEM_PROMPT
        from app.models.company import Project
        from app.models.conversation import ConversationProjectState
        from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeBaseMode
        from app.services.knowledge_base_capacity import require_direct_context_ready
        from app.services.personas.repository import PersonaRepository

        rows = (
            await self._db.execute(
                select(Project, KnowledgeBase, KnowledgeBaseDirectFile)
                .join(KnowledgeBase, Project.knowledge_base_id == KnowledgeBase.id)
                .outerjoin(
                    KnowledgeBaseDirectFile,
                    KnowledgeBaseDirectFile.knowledge_base_id == KnowledgeBase.id,
                )
                .where(Project.is_active.is_(True))
                .order_by(Project.name, Project.id)
            )
        ).all()
        normalized_message = normalize_vietnamese_text(user_text)
        matches = []
        for row in rows:
            project = row[0]
            names = [project.slug, project.name, *(project.aliases or [])]
            if any(
                re.search(
                    rf"(?<!\w){re.escape(normalize_vietnamese_text(name))}(?!\w)",
                    normalized_message,
                )
                for name in names
                if len(normalize_vietnamese_text(name)) >= 2
            ):
                matches.append(row)
        if len(matches) > 1:
            names = ", ".join(row[0].name for row in matches)
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
        if selected is None and focused_id is not None:
            selected = next((row for row in rows if row[0].id == focused_id), None)
        if selected is None:
            if focused_id is not None or getattr(
                conversation, "project_context_state", "EXPLORE"
            ) != ConversationProjectState.EXPLORE:
                conversation.project_context_state = ConversationProjectState.EXPLORE
                conversation.focused_project_id = None
                await self._db.commit()
            return ProjectTurnContext(state="EXPLORE")

        project, knowledge_base, direct_file = selected
        if focused_id != project.id or getattr(
            conversation, "project_context_state", "EXPLORE"
        ) != ConversationProjectState.FOCUSED:
            conversation.project_context_state = ConversationProjectState.FOCUSED
            conversation.focused_project_id = project.id
            await self._db.commit()

        direct_context = None
        if knowledge_base.mode is KnowledgeBaseMode.DIRECT_CONTEXT:
            provider = provider_from_conversation(conversation)
            persona_body = (
                await PersonaRepository(self._db).active_persona_body(provider)
            ) or AGENT_SYSTEM_PROMPT
            if direct_file is None:
                direct_context = DirectContext(
                    knowledge_base_id=str(knowledge_base.id),
                    persona_body=persona_body,
                    knowledge_text="",
                )
            else:
                await require_direct_context_ready(
                    self._db,
                    knowledge_base,
                    agent_markdown=persona_body,
                )
                direct_context = DirectContext(
                    knowledge_base_id=str(knowledge_base.id),
                    persona_body=persona_body,
                    knowledge_text=direct_file.normalized_text,
                )
        return ProjectTurnContext(
            state="FOCUSED",
            project_id=str(project.id),
            project_slug=project.slug,
            project_name=project.name,
            knowledge_mode=knowledge_base.mode.value,
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

    def __init__(self, db, embedder) -> None:
        self._db = db
        self._embedder = embedder

    async def try_answer(self, user_text: str):
        from app.core.vector import vec_literal
        from app.graph.ports import FaqBypassResult
        from app.graph.tools import _cached_embed
        from app.services.retrieval import RetrievalRepository
        from app.services.retrieval import faq_bypass as fb

        started = time.perf_counter()
        repo = RetrievalRepository(self._db)
        try:
            active_project_ids = getattr(repo, "active_project_ids", None)
            project_ids = await active_project_ids() if active_project_ids is not None else None
            if project_ids == []:
                return None
            emb = vec_literal(await _cached_embed(self._embedder, user_text))
            # Both arms are intentionally unscoped (no project_ids): the VFIC
            # deployment is single-tenant, mirroring search_bus_timetable's
            # deliberate NULL-slug choice. Re-scope only if the bot goes
            # multi-project (pass the conversation's project id into both calls).
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
        from app.services.errors import InstallationError
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


def build_minimax_extractor():
    """MiniMax extractor (safety model, temp 0) for candidate extraction."""
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _chat_for_role("safety", temperature=0.0)

    async def extractor(system: str, user: str) -> str:
        return (
            await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        ).content

    return extractor


def make_minimax_llm_json(
    *,
    minimax_api_key: str | None = None,
    openrouter_api_key: str | None = None,
):
    """(system, user) -> json_text callable for the LLM training pipeline.

    OpenAI-compatible MiniMax client with JSON-object response mode. Falls back to the
    agent model when MINIMAX_DIGEST_MODEL is unset. Imported lazily by the ingest worker
    only, so the app/tests never need langchain-openai at import time.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _chat_for_role(
        "digest",
        temperature=0.1,
        json_mode=True,
        minimax_api_key=minimax_api_key,
        openrouter_api_key=openrouter_api_key,
    )

    async def _call(system: str, user: str) -> str:
        return (
            await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        ).content

    return _call


def _build_fast_llm(*, minimax_config, openrouter_config):
    """Build the optional fast-tier LLM for low-complexity intents (Phase 5).

    Returns ``None`` when no fast model is configured on the active provider —
    ``MiniMaxAgent`` then no-ops the ``use_fast`` switch (every turn uses the
    primary reasoning model, the pre-tiering default).

    The fast model is built directly (not via ``_chat_for_role``) because the
    role factory hard-codes the agent/safety model names. Here we explicitly use
    ``minimax_fast_model`` / ``openrouter_fast_model`` so the tier is genuine.

    Only the single active provider's fast model is built — there is no runtime
    failover between providers (a deploy-time ``LLM_DEFAULT_PROVIDER`` switch
    changes the active provider for the whole process).
    """
    s = get_settings()
    mm_fast = (getattr(s, "minimax_fast_model", "") or "").strip()
    or_fast = (getattr(s, "openrouter_fast_model", "") or "").strip()

    try:
        if minimax_config.enabled and mm_fast and minimax_config.api_key:
            if minimax_config.default_provider != "openrouter":
                return _minimax_chat(mm_fast, temperature=0.3, api_key=minimax_config.api_key)
        if openrouter_config.enabled and or_fast and openrouter_config.api_key:
            return _openrouter_chat(
                or_fast,
                temperature=0.3,
                timeout=s.openrouter_request_timeout,
                api_key=openrouter_config.api_key,
                capture_reasoning=True,
            )
        return None
    except Exception:  # noqa: BLE001
        logger.warning("fast-tier LLM build failed; primary-only tier", exc_info=True)
        return None


# ── Process-wide LLM client cache ───────────────────────────────────────────
# The ChatOpenAI clients + embedder are expensive to construct (langchain_openai
# import + httpx/pydantic wiring). Caching them avoids rebuilding on every turn.
# Keyed by the minimax + openrouter integration-settings cache versions ONLY —
# the two providers whose settings actually drive agent_llm / embedder / fast_llm
# construction. Zalo is deliberately excluded: its config feeds the per-turn
# ZaloChannelSender (resolved fresh in build_deps), so an OA token rotation
# invalidating this cache would force a needless 5-7s LLM-client rebuild.
#
# Scope of the win:
# - Direct/ASGI path (start_direct_chat_turn): multiple turns share one event
#   loop + one _client_cache in the web process → the 2nd+ turn skips rebuild.
# - RQ fork-per-job path: each forked child starts with an empty cache (the
#   parent's cache cannot be inherited — ChatOpenAI wraps an httpx pool whose
#   sockets must not be shared across fork()). So under default RQ each child
#   builds once and exits; the per-turn win there is the asyncio.gather over
#   the resolve_* calls, not this cache. Moving chatbot turns off fork-per-job
#   (SimpleWorker) is what makes this cache bite on the worker path.
#
# ``_build_cached_clients`` is the single constructor; ``build_deps`` reads the
# cache and only re-binds the per-turn pieces (db session, retrieval repo, lead
# adapter, faq_bypass adapter, zalo config + sender with its refresh closure,
# followup gate).


@dataclass
class _CachedClients:
    agent_llm: object
    fast_llm: object | None
    embedder: object


_client_cache: dict[str, object] = {}
_client_cache_lock = asyncio.Lock()


async def _build_cached_clients(db) -> _CachedClients:  # noqa: RUF029 (async for lock)
    """Return the cached LLM client bundle, building it once per settings version.

    The cache key covers only the LLM providers (minimax + openrouter) whose
    settings actually drive ``agent_llm`` / ``embedder`` / ``fast_llm``
    construction. Zalo config is deliberately excluded — it feeds only the
    per-turn ``ZaloChannelSender`` (resolved separately in ``build_deps``), so
    a Zalo OA token refresh must NOT invalidate the expensive LLM clients.
    """
    from app.core.cache import cache_version
    from app.services.integration_settings import IntegrationSettingsService

    s = get_settings()
    integration_settings = IntegrationSettingsService(db, settings=s)

    mm_version = await cache_version("integration_minimax")
    or_version = await cache_version("integration_openrouter")
    cache_key = f"mm:{mm_version}|or:{or_version}"

    cached = _client_cache.get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    async with _client_cache_lock:
        # Re-check inside the lock: a concurrent turn may have built it.
        cached = _client_cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        # Sequential: both resolves share the same ``db`` session, and
        # SQLAlchemy AsyncSession does NOT permit concurrent operations on one
        # connection (InvalidRequestError: "provisioning a new connection;
        # concurrent operations are not permitted"). On a cache hit each resolve
        # is a sub-ms Redis read; the cold path (first turn after restart) pays
        # two serial DB round-trips instead of one, but that happens once per
        # process lifetime.
        minimax_config = await integration_settings.resolve_minimax()
        openrouter_config = await integration_settings.resolve_openrouter()
        agent_llm = _chat_for_role(
            "agent",
            temperature=0.3,
            minimax_api_key=minimax_config.api_key,
            openrouter_api_key=openrouter_config.api_key,
            minimax_enabled=minimax_config.enabled,
            openrouter_enabled=openrouter_config.enabled,
            default_provider=minimax_config.default_provider,
            openrouter_agent_model=openrouter_config.agent_model,
            openrouter_safety_model=openrouter_config.safety_model,
            openrouter_digest_model=openrouter_config.digest_model,
        )
        embedder = build_embedder(s, openrouter_api_key=openrouter_config.api_key)
        fast_llm = _build_fast_llm(
            minimax_config=minimax_config,
            openrouter_config=openrouter_config,
        )
        bundle = _CachedClients(
            agent_llm=agent_llm,
            fast_llm=fast_llm,
            embedder=embedder,
        )
        _client_cache.clear()  # only one live version at a time
        _client_cache[cache_key] = bundle
        logger.info("llm_client_cache built key=%s", cache_key)
        return bundle


def reset_client_cache() -> None:
    """Clear the LLM client cache. Tests use this between cases."""
    _client_cache.clear()


async def build_deps(db, *, session_factory=None):
    """Wire the full GraphDeps for one chatbot turn (agent + safety + embedder + zalo).

    The expensive LLM clients + embedder are cached process-wide (see
    ``_build_cached_clients``); this function only re-binds the per-turn pieces:
    the db session, retrieval/lead/faq_bypass adapters, the zalo sender (with
    its token-refresh closure), and the followup gate.

    ``session_factory`` (optional, an ``async_sessionmaker``) enables parallel tool
    dispatch: each concurrent tool call opens its own session via the factory
    instead of sharing ``db`` (which is NOT safe for concurrent use).
    """
    from app.services.conversation import ConversationService
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.profile_enrichment import ProfileEnrichmentService
    from app.services.retrieval import RetrievalRepository
    from app.services.zalo_sender import ZaloChannelSender

    clients = await _build_cached_clients(db)
    integration_settings = IntegrationSettingsService(db, settings=get_settings())

    # Zalo config is resolved per-turn (cheap — Redis-cached via cached_zalo_config)
    # so a rotated OA token takes effect on the very next turn without invalidating
    # the expensive LLM client cache.
    zalo_config = await integration_settings.resolve_zalo()
    zalo_sender = ZaloChannelSender(
        zalo_config,
        refresh=lambda: integration_settings.refresh_oa_access_token(),
    )

    async def _enrich_oa_profile(zalo_id: str, user_id: str) -> bool:
        return await ProfileEnrichmentService(db, zalo_sender).enrich_oa_user(
            zalo_id,
            user_id=user_id,
        )

    # Parallel tool dispatch: each concurrent tool call gets its own session so
    # the shared ``db`` is never used concurrently. Lazy import keeps the graph
    # layer free of concrete-service imports at module load.
    make_retrieval = None
    if session_factory is not None:

        @asynccontextmanager
        async def _make_retrieval():
            async with session_factory() as session:
                yield RetrievalRepository(session)

        make_retrieval = _make_retrieval

    return GraphDeps(
        db=db,
        agent=MiniMaxAgent(clients.agent_llm, clients.embedder, fast_llm=clients.fast_llm),
        embedder=clients.embedder,
        zalo=zalo_sender,
        conversation=ConversationService(db),
        retrieval=RetrievalRepository(db),
        make_retrieval=make_retrieval,
        lead=_LeadContextAdapter(db),
        faq_bypass=_FaqBypassAdapter(db, clients.embedder),
        followup_allowed=_make_followup_allowed(db),
        enrich_oa_profile=_enrich_oa_profile,
        runtime_policy=_RuntimePolicyAdapter(db),
        direct_context=_DirectContextAdapter(db),
    )


def _make_followup_allowed(db):
    from app.services.proactive.repository import conversation_allowed_by_followup_rules

    async def _allowed(conv):
        return await conversation_allowed_by_followup_rules(db, conv)

    return _allowed
