"""persistence_low RQ worker: candidate extraction after a bot send.

One job performs one LLM extraction and persists both lead_patch and memory_facts.
Job fns are sync (RQ); they asyncio.run the async services.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def enqueue_persist_candidate(job: dict) -> None:
    from app.workers.utils import enqueue_job

    enqueue_job("persistence_low", run_persist_candidate_job, job)


def enqueue_enrich_oa_profile(job: dict) -> None:
    """Enqueue a best-effort OA profile (avatar/name) enrichment job.

    Runs on the low-priority persistence queue so it never blocks the webhook
    acknowledgement path. Failures are logged inside the job and never raise.
    """
    from app.workers.utils import enqueue_job

    enqueue_job("persistence_low", run_enrich_oa_profile_job, job)


def run_enrich_oa_profile_job(job: dict) -> None:
    from app.workers.async_runner import run_async

    run_async(_enrich_oa_profile_async(job))


def run_persist_candidate_job(job: dict) -> None:
    from app.workers.async_runner import run_async

    run_async(_persist_candidate_async(job))


def _build_extractor():
    """MiniMax extractor for candidate extraction.

    Thin wrapper over the shared factory so candidate extraction reuses the same
    safety-LLM wiring as the chatbot agent.
    """
    from app.graph.factories import build_minimax_extractor

    return build_minimax_extractor()


async def _persist_candidate_async(job: dict) -> None:
    from app.graph.clients import build_embedder
    from app.services.candidate_extraction import CandidateExtractionService
    from app.services.integration_settings import IntegrationSettingsService
    from app.workers._db import worker_session

    try:
        async with worker_session() as db:
            openrouter_config = await IntegrationSettingsService(db).resolve_openrouter()
            await CandidateExtractionService.persist(
                db,
                build_embedder(openrouter_api_key=openrouter_config.api_key).batch,
                _build_extractor(),
                job["chat_id"],
                job.get("user_text", ""),
                job.get("bot_output", ""),
            )
    except Exception:
        logger.warning(
            "candidate extraction failed for chat %s; chat turn continues",
            job.get("chat_id"),
            exc_info=True,
        )


async def _enrich_oa_profile_async(job: dict) -> None:
    """Fetch avatar/name from Zalo OA and persist onto the lead (best-effort).

    Resolves live OA credentials (Redis-cached) so a rotated token takes effect
    on the next message without restarting the worker. The refresh callback on
    ``ZaloOASender`` handles one retry on a stale token.
    """
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.profile_enrichment import ProfileEnrichmentService
    from app.services.zalo_oa_service import ZaloOASender
    from app.workers._db import worker_session

    zalo_id = job.get("zalo_id") or ""
    user_id = job.get("user_id") or ""
    if not zalo_id or not user_id:
        return
    try:
        async with worker_session() as db:
            integration = IntegrationSettingsService(db)
            cfg = await integration.resolve_zalo()
            sender = ZaloOASender(
                access_token=cfg.oa_access_token,
                refresh=integration.refresh_oa_access_token,
            )
            await ProfileEnrichmentService(db, sender).enrich_oa_user(
                zalo_id, user_id=user_id
            )
    except Exception:
        logger.warning(
            "oa profile enrichment failed zalo_id=%s", zalo_id, exc_info=True
        )
