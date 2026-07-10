"""Chat-turn execution plus the RQ recovery adapter."""
from __future__ import annotations

import asyncio
import contextlib
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


def start_direct_chat_turn(job: dict) -> bool:
    """Schedule an interactive turn on the current ASGI event loop.

    The webhook has already committed the inbound message and acquired the
    database lock. A process restart is therefore recoverable by the offline
    reconciliation sweep; normal user turns never enter an RQ queue.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.exception("direct chat turn could not be scheduled")
        return False
    task = loop.create_task(_run_job_async(job, source="direct"))

    def _log_completion(completed: asyncio.Task[None]) -> None:
        try:
            completed.result()
        except asyncio.CancelledError:
            logger.warning("direct chat turn cancelled conversation=%s", job.get("conversation_id"))
        except Exception:
            logger.exception("direct chat turn failed conversation=%s", job.get("conversation_id"))

    task.add_done_callback(_log_completion)
    return True


async def _renew_direct_lock(job: dict) -> None:
    """Keep a direct turn's durable lease fresh without sharing its DB session."""
    conversation_id = job.get("conversation_id")
    lock_owner = job.get("lock_owner")
    if not conversation_id or not lock_owner:
        return

    import uuid

    from app.core.config import get_settings
    from app.core.db import async_session
    from app.services.conversation import ConversationService

    settings = get_settings()
    try:
        conv_id = uuid.UUID(str(conversation_id))
    except ValueError:
        logger.warning("direct chat turn has invalid conversation id=%r", conversation_id)
        return

    while True:
        await asyncio.sleep(settings.direct_turn_heartbeat_seconds)
        try:
            async with async_session() as db:
                renewed = await ConversationService(db).renew_lock(
                    conv_id, lock_owner=str(lock_owner)
                )
        except Exception:  # noqa: BLE001
            # A short database blip must not permanently disable lease renewal.
            # Retrying on the regular cadence stays well inside stale-lock detection.
            logger.warning(
                "direct chat turn lease heartbeat failed conversation=%s",
                conversation_id,
                exc_info=True,
            )
            continue
        if not renewed:
            logger.info("direct chat turn lease no longer owned conversation=%s", conversation_id)
            return


async def _bridge_typing(chat_id: str, bot_token: str | None = None) -> None:
    """Pulse the Zalo typing indicator until run_turn's heartbeat takes over.

    The webhook fires a one-shot typing ping that expires after ~3-5s, and the
    sustained ``_status_heartbeat`` only starts inside ``run_turn`` — after
    ``build_deps``. This bridge closes that gap so the indicator never vanishes
    during the preamble. It self-limits to a few pulses: once ``run_turn``'s
    heartbeat is running it is redundant, and the caller cancels it before send.
    All failures are swallowed (typing is best-effort).

    ``bot_token`` is the live DB-resolved token carried via the job dict so the
    pulses work in prod where the env ``ZALO_BOT_TOKEN`` is stale.
    """
    from app.core.config import get_settings

    interval = get_settings().typing_heartbeat_seconds
    for _ in range(4):  # ~14s max — enough to cover any realistic preamble
        try:
            from app.services.webhook import _fire_typing

            await _fire_typing(chat_id, bot_token)
        except Exception:  # noqa: BLE001
            return
        await asyncio.sleep(interval)





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
    """RQ chat-turn entrypoint (sync). Runs the async graph turn."""
    from app.workers.async_runner import run_async

    source = str(job.get("execution_source") or "queued")
    run_async(_run_job_async(job, source=source))


def preload_imports() -> None:
    """Import the heavy graph/LLM deps once in the parent worker process.

    RQ forks a child process (``os.fork``) for every job via
    ``Worker.fork_work_horse``. Without preloading, each forked child re-imports
    langchain/openai/google + the graph layer from scratch — a ~5-7s cost that
    dominated the per-turn preamble (measured ``preamble_ms`` avg 6.1s).

    Importing these modules in the parent *before* ``w.work()`` lets the forked
    child inherit them via copy-on-write, collapsing the preamble to <0.5s.
    Call this once from ``run_worker.main`` before entering the RQ work loop.
    """
    import time as _time  # noqa: F401  — used for the startup log below

    t0 = _time.monotonic()
    # Core async + DB plumbing (cheap, but keeps the loop/engine singletons warm)
    import app.workers.async_runner  # noqa: F401
    import app.workers._db  # noqa: F401

    # Heavy graph + LLM stack — these are the real import cost on a cold process.
    import app.graph.factories  # noqa: F401  — pulls build_deps + all graph deps
    import app.graph.runner  # noqa: F401
    import app.graph.clients  # noqa: F401  — pulls langchain_openai, httpx
    import app.graph.tools  # noqa: F401
    import app.graph.context  # noqa: F401
    # Touch the LLM client constructors so their langchain imports are realized.
    from app.graph.clients import MiniMaxAgent, MiniMaxSafety  # noqa: F401

    elapsed = _time.monotonic() - t0
    logger.info("worker preload_imports completed in %.1fs", elapsed)


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


async def _run_job_async(job: dict, *, source: str = "recovery") -> None:
    # Imported lazily so importing this module (e.g. in tests) does NOT pull in the
    # heavy LLM/Google deps — those are only needed for a real run.
    from app.workers._db import worker_session, worker_session_factory
    from app.graph.factories import build_deps
    from app.graph.runner import BotRunState, run_turn

    # Wall-clock at job entry (epoch) so run_turn can split the enqueue→turn-start
    # preamble (build_deps + Phase-0 scan) from the webhook→pickup gap. Both are
    # measured inside this worker process, so time.time() (epoch) is fine.
    job_start_epoch = time.time()

    # RQ jobs retain a queue-depth snapshot. Direct turns do not touch
    # the queue, so a missing value is meaningful telemetry.
    queue_depth: int | None = None
    if source != "direct":
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
        reply_to_message_id=job.get("reply_to_message_id", ""),
        lock_owner=str(job.get("lock_owner") or ""),
        received_at_epoch=received_at_epoch,
        deadline_at_epoch=(received_at_epoch + sla) if received_at_epoch else 0.0,
        preamble_start_epoch=job_start_epoch,
        queue_depth=queue_depth,
        execution_source=source,
    )
    heartbeat_task = (
        asyncio.create_task(_renew_direct_lock(job)) if source == "direct" else None
    )
    # Bridge the Bot typing indicator across the preamble. The webhook's one-shot
    # typing expires after ~3-5s; without this, the indicator vanishes during
    # build_deps and the user perceives a long "no status" gap. The bridge pulses
    # until run_turn's own _status_heartbeat takes over, then is cancelled. No-op
    # for OA (no typing API) and for jobs that predate zalo_chat_id.
    zalo_channel = str(job.get("zalo_channel") or "")
    bridge_task: asyncio.Task[None] | None = None
    if zalo_channel == "bot" and job.get("zalo_chat_id"):
        bridge_task = asyncio.create_task(
            _bridge_typing(job["zalo_chat_id"], job.get("zalo_bot_token"))
        )
    try:
        async with worker_session() as db:
            deps = await build_deps(db, session_factory=worker_session_factory())
            deps.persist = _enqueue_persist  # wire candidate extraction on SENT
            # build_deps is done — run_turn's heartbeat will take over now.
            if bridge_task is not None:
                bridge_task.cancel()
            started_at = _now()
            try:
                await run_turn(state, deps)
            except LLMThrottled:
                # LLM is throttled — send a static reply without another model call.
                logger.warning("llm_throttled: sending degradation reply for %s", job.get("conversation_id", "?"))
                try:
                    from app.services.conversation import ConversationService

                    svc = ConversationService(db)
                    conv = await svc.get(uuid.UUID(state.conversation_id))
                    if conv is not None:
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
                            if state.reply_to_message_id:
                                send_result = await sender.send_message(
                                    conv.zalo_chat_id,
                                    DEGRADATION_REPLY,
                                    quote_message_id=state.reply_to_message_id,
                                )
                            else:
                                send_result = await sender.send_message(
                                    conv.zalo_chat_id, DEGRADATION_REPLY
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
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                logger.warning("direct chat turn lease heartbeat failed", exc_info=True)
        if bridge_task is not None:
            bridge_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await bridge_task
