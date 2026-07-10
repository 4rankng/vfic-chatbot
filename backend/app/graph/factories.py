"""Dependency factories for the graph's LLM/embedder wiring.

- ``build_deps`` wires the full ``GraphDeps`` for the chatbot worker.
- ``build_minimax_extractor`` — candidate extraction (persistence worker).
- ``make_minimax_llm_json`` — JSON-mode LLM for the knowledge training pipeline (ingest worker).

langchain_openai is imported lazily inside each factory so the web-process import path
stays langchain-free.
"""

from __future__ import annotations

import logging
import time

from app.core.config import get_settings
from app.graph.clients import (
    MiniMaxAgent,
    MiniMaxSafety,
    _chat_for_role,
    _minimax_chat,
    _openrouter_chat,
    build_embedder,
)
from app.graph.types import GraphDeps

logger = logging.getLogger(__name__)


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

    def ensure(self, reply: str, question: str) -> str:
        from app.services.lead.probing import ensure_lead_collection_question

        return ensure_lead_collection_question(reply, question)


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
            emb = vec_literal(await _cached_embed(self._embedder, user_text))
            # Both arms are intentionally unscoped (no project_ids): the VFIC
            # deployment is single-tenant, mirroring search_bus_timetable's
            # deliberate NULL-slug choice. Re-scope only if the bot goes
            # multi-project (pass the conversation's project id into both calls).
            vector_rows = await repo.match_faq(
                emb, top_k=fb.TOP_K, floor=fb.CANDIDATE_VECTOR_FLOOR
            )
            lexical_rows = await repo.match_faq_lexical(
                user_text, top_k=fb.TOP_K, threshold=fb.TRIGRAM_THRESHOLD
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
            decision.decision, decision.tier, decision.top1_score,
            decision.top2_score, decision.margin,
            decision.scored.vec_sim if decision.scored else 0.0,
            decision.scored.tri_sim if decision.scored else 0.0,
            decision.reason, latency_ms,
            decision.scored.faq_id if decision.scored else None,
        )
        if (
            decision.decision == fb.DECISION_ACCEPT
            and decision.scored
            and decision.scored.answer
        ):
            return FaqBypassResult(
                answer=decision.scored.answer,
                faq_id=decision.scored.faq_id,
                tier=decision.tier,
                score=decision.top1_score,
                reason=decision.reason,
            )
        return None


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

    Returns ``None`` when no fast model is configured on either provider —
    ``MiniMaxAgent`` then no-ops the ``use_fast`` switch (every turn uses the
    primary reasoning model, the pre-tiering default).

    The fast model is built directly (not via ``_chat_for_role``) because the
    role factory hard-codes the agent/safety model names. Here we explicitly use
    ``minimax_fast_model`` / ``openrouter_fast_model`` so the tier is genuine.
    """
    s = get_settings()
    mm_fast = (getattr(s, "minimax_fast_model", "") or "").strip()
    or_fast = (getattr(s, "openrouter_fast_model", "") or "").strip()
    if not mm_fast and not or_fast:
        return None

    try:
        primary = None
        fallback = None
        if mm_fast and minimax_config.enabled and minimax_config.api_key:
            primary = _minimax_chat(
                mm_fast,
                temperature=0.3,
                api_key=minimax_config.api_key,
            )
        if or_fast and openrouter_config.enabled and openrouter_config.api_key:
            or_llm = _openrouter_chat(
                or_fast,
                temperature=0.3,
                timeout=s.openrouter_request_timeout,
                api_key=openrouter_config.api_key,
            )
            if primary is not None:
                from app.graph.clients import FallbackLLM

                # Respect the configured default provider ordering.
                if minimax_config.default_provider == "openrouter":
                    return FallbackLLM(or_llm, primary)
                return FallbackLLM(primary, or_llm)
            return or_llm
        return primary
    except Exception:  # noqa: BLE001
        logger.warning("fast-tier LLM build failed; falling back to primary only", exc_info=True)
        return None


async def build_deps(db):
    """Wire the full GraphDeps for one chatbot turn (agent + safety + embedder + zalo)."""
    from app.services.conversation import ConversationService
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.retrieval import RetrievalRepository
    from app.services.zalo_sender import ZaloChannelSender

    s = get_settings()
    integration_settings = IntegrationSettingsService(db, settings=s)
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
    safety_llm = _chat_for_role(
        "safety",
        temperature=0.0,
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
    zalo_config = await integration_settings.resolve_zalo()
    fast_llm = _build_fast_llm(
        minimax_config=minimax_config,
        openrouter_config=openrouter_config,
    )
    return GraphDeps(
        db=db,
        agent=MiniMaxAgent(agent_llm, embedder, fast_llm=fast_llm),
        safety=MiniMaxSafety(safety_llm),
        embedder=embedder,
        zalo=ZaloChannelSender(
            zalo_config,
            refresh=lambda: integration_settings.refresh_oa_access_token(),
        ),
        conversation=ConversationService(db),
        retrieval=RetrievalRepository(db),
        lead=_LeadContextAdapter(db),
        faq_bypass=_FaqBypassAdapter(db, embedder),
        followup_allowed=_make_followup_allowed(db),
    )


def _make_followup_allowed(db):
    from app.services.proactive.repository import conversation_allowed_by_followup_rules

    async def _allowed(conv):
        return await conversation_allowed_by_followup_rules(db, conv)

    return _allowed
