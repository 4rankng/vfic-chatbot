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


def enqueue_enrich_messenger_profile(job: dict) -> None:
    """Enqueue a best-effort Messenger profile (name/avatar/gender) enrichment job.

    Same low-priority queue as the OA equivalent so the Graph call never sits in
    the webhook acknowledgement path. Failures are logged inside the job.
    """
    from app.workers.utils import enqueue_job

    enqueue_job("persistence_low", run_enrich_messenger_profile_job, job)


def run_enrich_messenger_profile_job(job: dict) -> None:
    from app.workers.async_runner import run_async

    run_async(_enrich_messenger_profile_async(job))


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
    from app.composition.recruitment import run_candidate_persistence
    from app.graph.clients import build_embedder
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.installation.service import InstallationService
    from app.workers._db import worker_session

    try:
        async with worker_session() as db:
            revision_id = str(job.get("runtime_revision_id") or "")
            authority_generation = job.get("authority_generation")
            fingerprint = str(job.get("runtime_fingerprint") or "")
            stamped = bool(revision_id or authority_generation is not None or fingerprint)
            if stamped:
                active = await InstallationService(db).resolve_active()
                is_current = (
                    active is not None
                    and revision_id == str(active.revision.id)
                    and authority_generation == active.fingerprint.authority_generation
                    and fingerprint == active.fingerprint.checksum()
                    and "candidate_intake" in active.revision.capability_ids
                )
                if not is_current:
                    logger.info("candidate extraction suppressed by runtime authority")
                    return
            openrouter_config = await IntegrationSettingsService(db).resolve_openrouter()
            await run_candidate_persistence(
                db,
                embed_batch=build_embedder(
                    openrouter_api_key=openrouter_config.api_key
                ).batch,
                extractor=_build_extractor(),
                chat_id=job["chat_id"],
                user_text=job.get("user_text", ""),
                bot_output=job.get("bot_output", ""),
                expected_conversation_version=job.get("conversation_version"),
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
                zalo_id,
                user_id=user_id,
                wait_for_inflight=True,
            )
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        logger.warning(
            "oa profile enrichment failed error_type=%s",
            type(exc).__name__,
        )


async def _enrich_messenger_profile_async(job: dict) -> None:
    """Fetch name/avatar/gender from the Messenger User Profile API.

    Gender is what lets the bot say "anh" or "chị" instead of the neutral
    "anh/chị". It requires both the ``pages_user_gender`` permission and the
    Business Asset User Profile Access feature, so an absent gender is an
    expected outcome rather than a failure — the prompt layer stays neutral.
    """
    from app.channels.providers.facebook_oauth import get_user_profile
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.profile_enrichment import ProfileEnrichmentService
    from app.workers._db import worker_session

    psid = job.get("psid") or ""
    page_id = job.get("page_id") or ""
    if not psid or not page_id:
        return
    try:
        async with worker_session() as db:
            cfg = await IntegrationSettingsService(db).resolve_facebook(page_id)
            if cfg is None or not cfg.page_access_token:
                return

            async def _fetch(target_psid: str):
                return await get_user_profile(cfg, psid=target_psid)

            await ProfileEnrichmentService(db).enrich_messenger_user(
                psid,
                page_id=page_id,
                fetch_profile=_fetch,
                wait_for_inflight=True,
            )
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        logger.warning(
            "messenger profile enrichment failed error_type=%s",
            type(exc).__name__,
        )
