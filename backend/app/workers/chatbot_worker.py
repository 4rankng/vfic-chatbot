"""RQ worker: enqueue + run chatbot turns on the webhook_high queue."""
from __future__ import annotations

import logging
import time
import uuid

from app.graph.llm_semaphore import LLMThrottled
from app.graph.types import _now

logger = logging.getLogger(__name__)

# Static Vietnamese degradation message — sent when LLM is throttled (no LLM call).
DEGRADATION_REPLY = (
    "Xin lỗi bạn, hiện tại hệ thống đang gặp nhiều truy cập đồng thời. "
    "Vui lòng gửi lại tin nhắn sau ít phút nhé. Cảm ơn bạn!"
)


def enqueue_chat_run(job: dict) -> bool:
    """Enqueue a bot turn onto the webhook_high RQ queue.

    Returns False when the enqueue fails (e.g. Redis down) or the queue depth
    exceeds ``chat_queue_max_depth`` (backpressure).  The caller should propagate
    this as a 503 so Zalo retries.
    """
    from app.core.config import get_settings
    from app.workers.utils import enqueue_job

    s = get_settings()
    return enqueue_job(
        "webhook_high",
        run_chat_turn_job,
        job,
        job_timeout=s.chat_turn_job_timeout,
        max_depth=s.chat_queue_max_depth or None,
    )


def run_chat_turn_job(job: dict) -> None:
    """RQ job entrypoint (sync). Runs the async graph turn."""
    from app.workers.async_runner import run_async

    run_async(_run_job_async(job))


def _enqueue_persist(persist_job: dict) -> None:
    """Fire candidate extraction after a SENT reply (best-effort)."""
    from app.workers.persistence_worker import enqueue_persist_candidate

    enqueue_persist_candidate(persist_job)


def _preamble_timings(state, started_at, *, lane: str, throttle: bool = False) -> dict:
    """Build the partial ``stage_timings`` slice the worker can compute.

    Covers only the enqueue/preamble/queue-depth slice (the normal full dict is
    built by ``run_turn``). Used on the LLMThrottled degradation path, which
    the worker owns end-to-end, so the dashboard can still attribute a degraded
    turn to a stage and flag it via ``throttle: True``.
    """
    timings: dict = {"lane": lane}
    if state.queue_depth is not None:
        timings["queue_depth"] = state.queue_depth
    if throttle:
        timings["throttle"] = True
    if state.received_at_epoch > 0 and state.preamble_start_epoch > 0:
        timings["webhook_to_pickup_ms"] = max(
            0, int(round((state.preamble_start_epoch - state.received_at_epoch) * 1000))
        )
    if started_at is not None and state.preamble_start_epoch > 0:
        timings["preamble_ms"] = max(
            0, int(round((started_at.timestamp() - state.preamble_start_epoch) * 1000))
        )
    return timings


async def _run_job_async(job: dict) -> None:
    # Imported lazily so importing this module (e.g. in tests) does NOT pull in the
    # heavy LLM/Google deps — those are only needed for a real run.
    from app.workers._db import worker_session
    from app.graph.factories import build_deps
    from app.graph.runner import BotRunState, run_turn

    # Wall-clock at job entry (epoch) so run_turn can split the enqueue→turn-start
    # preamble (build_deps + Phase-0 scan) from the webhook→pickup gap. Both are
    # measured inside this worker process, so time.time() (epoch) is fine.
    job_start_epoch = time.time()

    # ── Phase 0 observability: snapshot webhook_high depth at job start ──
    # Carried into BotRunState.stage_timings (queue_depth) so the performance
    # dashboard can correlate latency spikes with saturation. Best-effort —
    # never breaks a turn. (busy/total worker counts are read live by
    # /health/queue and /admin/performance, so they aren't stored per-turn.)
    queue_depth: int | None = None
    try:
        from rq import Queue

        from app.core.redis import get_redis_sync

        queue_depth = Queue("webhook_high", connection=get_redis_sync()).count
    except Exception:  # noqa: BLE001
        pass

    from app.core.config import get_settings

    received_at_epoch = float(job.get("received_at_epoch") or 0.0)
    sla = get_settings().sla_seconds
    state = BotRunState(
        conversation_id=job["conversation_id"],
        version_at_start=int(job["version_at_start"]),
        user_text=job["user_text"],
        user_name=job.get("user_name", ""),
        lock_owner=str(job.get("lock_owner") or ""),
        received_at_epoch=received_at_epoch,
        deadline_at_epoch=(received_at_epoch + sla) if received_at_epoch else 0.0,
        preamble_start_epoch=job_start_epoch,
        queue_depth=queue_depth,
    )
    async with worker_session() as db:
        deps = await build_deps(db)
        deps.persist = _enqueue_persist  # wire candidate extraction on SENT
        started_at = _now()
        try:
            await run_turn(state, deps)
        except LLMThrottled:
            # LLM is throttled — send static degradation msg (no LLM call).
            # Must record_bot_outcome to clear the per-chat mutex (bot_locked_until),
            # otherwise the conversation is stalled until TTL expiry (~3 min).
            logger.warning("llm_throttled: sending degradation reply for %s", job.get("conversation_id", "?"))
            try:
                from app.services.conversation import ConversationService

                svc = ConversationService(db)
                conv = await svc.get(uuid.UUID(state.conversation_id))
                if conv is not None:
                    # A throttled turn may have outlasted a recruiter takeover —
                    # re-check ownership before sending so a degradation bubble
                    # never lands in a human-owned chat (mirrors run_turn's
                    # pre_send_guard). Not owned → record SUPPRESSED, no send.
                    await db.refresh(conv)
                    lock_owner = state.lock_owner or None
                    owned = await svc.claim_send(
                        conv,
                        version_at_start=state.version_at_start,
                        lock_owner=lock_owner,
                        pending_message_id=state.pending_message_id,
                        reply=DEGRADATION_REPLY,
                    )
                    sent = False
                    external_error: str | None = None
                    zalo_message_id: str | None = None
                    if owned:
                        sender = (
                            deps.zalo.for_conversation(conv)
                            if hasattr(deps.zalo, "for_conversation")
                            else deps.zalo
                        )
                        send_result = await sender.send_message(
                            conv.zalo_chat_id,
                            DEGRADATION_REPLY,
                        )
                        sent = send_result.ok
                        external_error = None if send_result.ok else send_result.error
                        zalo_message_id = send_result.msg_id
                    throttle_timings = _preamble_timings(
                        state, started_at, lane="agent", throttle=True
                    )
                    await svc.record_bot_outcome(
                        conv,
                        version_at_start=state.version_at_start,
                        reply=DEGRADATION_REPLY,
                        started_at=started_at,
                        sent=sent,
                        pending_message_id=state.pending_message_id,
                        external_error=external_error,
                        zalo_message_id=zalo_message_id,
                        stage_timings=throttle_timings,
                        lock_owner=lock_owner,
                    )
            except Exception:  # noqa: BLE001
                logger.error("failed to send degradation reply", exc_info=True)
