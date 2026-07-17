"""Chat-turn execution plus the RQ recovery adapter."""

from __future__ import annotations

import asyncio
from inspect import iscoroutinefunction
import contextlib
import logging
import time
import uuid

from app.core.logging import trace_id_ctx
from app.graph.llm_semaphore import LLMThrottled
from app.graph.outbound_telemetry import OutboundTelemetry
from app.graph.send_classification import AMBIGUOUS_SEND_CLASSES
from app.graph.types import _now
from app.models.conversation import DeliveryStatus

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

    ``bot_token`` is accepted for backwards compatibility with legacy queued
    jobs that still carry it. When it is None (the v2 payload), the live token
    is resolved fresh from the DB so no secret rides the queue payload.
    """
    from app.core.config import get_settings

    interval = get_settings().typing_heartbeat_seconds
    for _ in range(4):  # ~14s max — enough to cover any realistic preamble
        try:
            token = bot_token
            if token is None:
                # Resolve the live DB token (env ZALO_BOT_TOKEN is stale in prod).
                # Best-effort: if resolution fails, _fire_typing falls back to env.
                from app.core.db import async_session
                from app.services.integration_settings import IntegrationSettingsService

                async with async_session() as db:
                    cfg = await IntegrationSettingsService(db).resolve_zalo()
                    token = cfg.bot_token
            from app.services.webhook import _fire_typing

            await _fire_typing(chat_id, token)
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
    """Import the heavy graph/LLM deps once in the worker process.

    ``run_worker`` uses ``SimpleWorker`` (no ``os.fork`` per job), so jobs run
    in-process and these imports stay warm for every turn. Combined with
    ``_build_cached_clients`` (which reuses the ChatOpenAI clients across turns),
    this removes the ~5-7s cold-import + client-construction cost that dominated
    the per-turn preamble under the old fork-per-job model (measured
    ``preamble_ms`` avg 6.1s, p95 10.9s). Call once from ``run_worker.main``
    before entering the work loop.
    """
    import time as _time  # noqa: F401  — used for the startup log below

    t0 = _time.monotonic()
    # Core async + DB plumbing (cheap, but keeps the loop/engine singletons warm)
    import app.workers.async_runner  # noqa: F401
    import app.workers._db  # noqa: F401

    # Heavy graph + LLM stack — these are the real import cost on a cold process.
    import app.graph.factories  # noqa: F401  — pulls build_deps + all graph deps
    import app.graph.runner  # noqa: F401
    import app.graph.clients  # noqa: F401  — client wrappers; SDKs stay lazy
    import app.graph.tools  # noqa: F401
    import app.graph.context  # noqa: F401

    # Client construction imports these lazily. Import them explicitly so the
    # first turn does not pay the multi-second SDK import cost.
    import langchain_core.messages  # noqa: F401
    import langchain_openai  # noqa: F401

    # Touch the wrappers used by the graph after the SDK modules are warm.
    from app.graph.clients import MiniMaxAgent  # noqa: F401

    elapsed = _time.monotonic() - t0
    logger.info("worker preload_imports completed in %.1fs", elapsed)


async def warm_llm_client_cache() -> None:
    """Build the process-wide LLM clients once, before the work loop.

    ``preload_imports`` warms the module imports; this finishes the job by
    constructing the ChatOpenAI + embedder clients into ``_client_cache``, so
    the first real candidate turn skips the ~5-7s cold-construction cost that
    otherwise dominates the ``preamble_ms`` p95 tail after every worker restart.

    Must run on the same event loop as jobs (``run_async`` from
    ``async_runner`` reuses the process-local singleton loop), so the lazily
    created DB engine and the loop-bound ``_client_cache_lock`` are shared with
    every subsequent turn — see ``factories._build_cached_clients``. Uses
    ``_build_cached_clients`` directly (not ``build_deps``): startup only needs
    the expensive client construction, not the per-turn Zalo/retrieval/lead
    wiring, which is cheap and resolved fresh each turn anyway.

    Failures here are non-fatal: ``run_worker`` wraps the call in a try/except
    and logs at ERROR, then proceeds to ``w.work()`` — the first turn rebuilds
    on demand. This mirrors the ``preload_imports`` degradation contract.
    """
    from app.workers._db import worker_session
    from app.graph.factories import _build_cached_clients

    async with worker_session() as db:
        await _build_cached_clients(db)


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
        timings["degraded"] = True
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
    # Top-level crash-guard: under SimpleWorker (no fork), an unhandled exception
    # here would kill the worker process and interrupt every queued turn. The
    # direct/ASGI path is the trusted no-fork precedent and relies on the same
    # guarantee. run_turn has its own try/finally for the per-turn cleanup
    # (status heartbeat cancellation); this guard is for failures OUTSIDE that
    # (build_deps, BotRunState construction, the worker's own LLMThrottled path).
    #
    # Re-raises cooperative-control exceptions (CancelledError on job timeout /
    # worker shutdown, KeyboardInterrupt, SystemExit) so they're not swallowed —
    # catching BaseException here would break graceful shutdown. Everything else
    # is logged and suppressed so one bad job can't take the worker down.
    try:
        await _run_job_async_inner(job, source=source)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        logger.exception(
            "chat turn crashed (conversation=%s); suppressed to protect the worker",
            job.get("conversation_id", "?"),
        )


async def _run_job_async_inner(job: dict, *, source: str = "recovery") -> None:
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
    # End-to-end trace id carried from the webhook through the RQ job dict.
    # Contextvars do not cross processes, so re-stash it here so every structured
    # log line inside the turn carries the originating request's id.
    trace_id = str(job.get("trace_id") or "")
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
        trace_id=trace_id,
        runtime_revision_id=str(job.get("runtime_revision_id") or ""),
        authority_generation=(
            int(job["authority_generation"])
            if job.get("authority_generation") is not None
            else None
        ),
        runtime_fingerprint=str(job.get("runtime_fingerprint") or ""),
    )
    heartbeat_task = asyncio.create_task(_renew_direct_lock(job)) if source == "direct" else None
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
    _trace_token = None
    try:
        # Set the trace contextvar inside the try so the finally always resets
        # it — if set before the try and BotRunState/bridge setup raised, the
        # token would leak into the next job on this worker process.
        _trace_token = trace_id_ctx.set(trace_id or "-")
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
                logger.warning(
                    "llm_throttled: sending degradation reply for %s",
                    job.get("conversation_id", "?"),
                )
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
                            outbox_channel=(
                                "zalo_oa"
                                if getattr(conv, "zalo_channel", "bot") == "oa"
                                else "zalo_bot"
                            ),
                            outbox_payload={
                                "chat_id": conv.zalo_chat_id,
                                "text": DEGRADATION_REPLY,
                                **(
                                    {"quote_message_id": state.reply_to_message_id}
                                    if state.reply_to_message_id
                                    else {}
                                ),
                            },
                        )
                        sent = False
                        external_error: str | None = None
                        zalo_message_id: str | None = None
                        degradation_override: DeliveryStatus | None = None
                        if owned:
                            sender = (
                                deps.zalo.for_conversation(conv)
                                if hasattr(deps.zalo, "for_conversation")
                                else deps.zalo
                            )
                            dispatch = getattr(svc, "dispatch_outbound_message", None)
                            send_t0 = time.monotonic()
                            if callable(dispatch) and iscoroutinefunction(dispatch):
                                send_result = await dispatch(message_id=state.pending_message_id)
                            elif state.reply_to_message_id:
                                send_result = await sender.send_message(
                                    conv.zalo_chat_id,
                                    DEGRADATION_REPLY,
                                    quote_message_id=state.reply_to_message_id,
                                )
                            else:
                                send_result = await sender.send_message(
                                    conv.zalo_chat_id, DEGRADATION_REPLY
                                )
                            if send_result is None:
                                from app.services.zalo_bot_service import SendResult

                                send_result = SendResult(
                                    ok=False,
                                    error="outbound command was not available for dispatch",
                                )
                            send_elapsed_ms = int(round((time.monotonic() - send_t0) * 1000))
                            sent = send_result.ok
                            external_error = None if send_result.ok else send_result.error
                            zalo_message_id = send_result.msg_id
                            # Mirror the runner's SEND_UNKNOWN classifier so a
                            # degradation reply that times out at Zalo is also
                            # non-retriable (at-most-once).
                            if (
                                not send_result.ok
                                and send_result.error_class in AMBIGUOUS_SEND_CLASSES
                            ):
                                degradation_override = DeliveryStatus.SEND_UNKNOWN
                        throttle_timings = _preamble_timings(
                            state, started_at, lane="agent", throttle=True
                        )
                        if owned:
                            throttle_timings["send_ms"] = max(0, send_elapsed_ms)
                            telemetry = getattr(send_result, "telemetry", None)
                            if isinstance(telemetry, OutboundTelemetry):
                                throttle_timings.update(telemetry.to_stage_timings())
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
                            delivery_status=degradation_override,
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
        if _trace_token is not None:
            trace_id_ctx.reset(_trace_token)
