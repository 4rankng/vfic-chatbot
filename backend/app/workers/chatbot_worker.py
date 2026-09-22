"""Chat-turn execution plus the RQ recovery adapter."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid

from app.core.logging import trace_id_ctx
from app.graph.llm_semaphore import LLMThrottled
from app.graph.types import _now

logger = logging.getLogger(__name__)
_direct_turn_tasks: set[asyncio.Task[None]] = set()
_DIRECT_TURN_SHUTDOWN_TIMEOUT_SECONDS = 5.0

# When every LLM provider is exhausted, NOTHING is sent to the customer: an
# internal-capacity apology reads as a broken bot (and was never true — the
# failure is quota/rate-limit, not traffic). The failure belongs to engineers,
# so the worker logs full diagnostics and records the turn as SUPPRESSED.
# See the LLMThrottled handler in _run_job_async_inner.


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
    _direct_turn_tasks.add(task)

    def _log_completion(completed: asyncio.Task[None]) -> None:
        _direct_turn_tasks.discard(completed)
        try:
            completed.result()
        except asyncio.CancelledError:
            logger.warning("direct chat turn cancelled conversation=%s", job.get("conversation_id"))
        except Exception:
            logger.exception("direct chat turn failed conversation=%s", job.get("conversation_id"))

    task.add_done_callback(_log_completion)
    return True


async def drain_direct_chat_turns(*, timeout_seconds: float | None = None) -> None:
    """Finish direct turns when possible, then cancel and drain stragglers."""
    timeout = (
        _DIRECT_TURN_SHUTDOWN_TIMEOUT_SECONDS
        if timeout_seconds is None
        else timeout_seconds
    )
    pending = {task for task in _direct_turn_tasks if not task.done()}
    if not pending:
        return
    _done, pending = await asyncio.wait(pending, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


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
    All failures are swallowed (typing is best-effort) — the bridge stops
    pulsing if either DB resolution or the typing POST raises; it does NOT
    fall back to the stale env ZALO_BOT_TOKEN (which 401s in prod).

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
                # Resolve the live DB token. If resolution raises (DB blip,
                # cipher issue, empty config), the outer except stops the
                # bridge — typing simply vanishes, which is safe.
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


def enqueue_recovery_chat_run(job: dict) -> bool:
    """Enqueue a recovered turn onto the low-priority ``recovery`` queue.

    The reconcile sweep re-answers conversations whose turn was lost, which can
    arrive in batches of dozens after an outage. On the live queue those batches
    queue ahead of candidate-visible turns — the 2026-09-22 storm put 62 recovery
    turns in front of live traffic and produced a 30-115s
    ``webhook_to_pickup_ms``. ``worker-chatbot`` consumes ``webhook_high`` first
    and ``recovery`` second, so a recovery backlog can never delay a live turn.
    Backpressure and timeout semantics match the live queue.
    """
    from app.core.config import get_settings
    from app.workers.utils import enqueue_job

    s = get_settings()
    return enqueue_job(
        "recovery",
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


def _abandoned_turn_timings(job: dict) -> dict:
    """Minimal ``stage_timings`` slice for a turn that never reached ``run_turn``.

    Mirrors :func:`_preamble_timings` without needing a ``BotRunState``: a turn
    can die before the state exists (build_deps, imports), and the dashboard
    still has to attribute the failure to the enqueue/pickup stage.
    """
    timings: dict = {"lane": "unknown", "degraded": True}
    received_at_epoch = float(job.get("received_at_epoch") or 0.0)
    if received_at_epoch > 0:
        timings["webhook_to_pickup_ms"] = max(
            0, int(round((time.time() - received_at_epoch) * 1000))
        )
    return timings


async def _record_abandoned_turn(job: dict, *, exc: BaseException) -> None:
    """Record a turn that died before ``run_turn`` could log an outcome.

    Without this, the crash guard below hid real failures: RQ's death penalty
    raises ``JobTimeoutException`` *inside* the job, and because the guard
    suppresses it, RQ recorded the job as successful. The conversation kept an
    unanswered inbound message and its per-chat lock, so the reconcile sweep
    re-enqueued the same turn every ~60s — measured in production as 298k
    stale-lock breaks and 300k re-enqueues against 352 recorded runs — and the
    dashboard showed a healthy pickup metric the whole time the bot answered
    nobody (2026-09-21: zero bot_runs recorded for a full day of inbound
    traffic). One ERROR BotRun + FAILED BOT row makes the failure visible, puts
    the sender in the console's failed-reply view, and frees the lock.

    Best-effort by design: the guard exists so a bad job cannot kill the worker,
    so a recording failure must never raise either.
    """
    conversation_id = str(job.get("conversation_id") or "")
    if not conversation_id:
        return

    from rq.timeouts import JobTimeoutException

    from app.core.config import get_settings
    from app.models.conversation import DeliveryStatus
    from app.services.conversation import ConversationService
    from app.workers._db import worker_session

    if isinstance(exc, JobTimeoutException):
        reason = (
            f"chat turn exceeded the {get_settings().chat_turn_job_timeout}s job timeout"
        )
    else:
        reason = f"chat turn crashed: {type(exc).__name__}"

    try:
        async with worker_session() as db:
            svc = ConversationService(db)
            conv = await svc.get(uuid.UUID(conversation_id))
            if conv is None:
                logger.error(
                    "abandoned chat turn has no conversation conversation=%s",
                    conversation_id,
                )
                return
            await db.refresh(conv)
            await svc.record_bot_outcome(
                conv,
                version_at_start=int(job.get("version_at_start") or conv.version),
                reply="",  # nothing reached the customer
                started_at=_now(),
                sent=False,
                # PENDING, not FAILED: this is the "turn started but never
                # completed" state, which keeps the reconcile sweep's fast
                # crash-recovery path (~2-4 min) instead of a delivery-failure
                # retry. The ERROR outcome + external_error still surface the
                # failure on the dashboard and in the console.
                delivery_status=DeliveryStatus.PENDING,
                external_error=reason,
                stage_timings=_abandoned_turn_timings(job),
                lock_owner=job.get("lock_owner") or None,
                trace_id=str(job.get("trace_id") or "") or None,
            )
        logger.error(
            "abandoned chat turn recorded conversation=%s reason=%s",
            conversation_id,
            reason,
        )
    except Exception:  # noqa: BLE001 — recording must never take the worker down
        logger.exception(
            "failed to record abandoned chat turn conversation=%s", conversation_id
        )


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
    # is logged, recorded as an ERROR outcome, and suppressed so one bad job
    # can't take the worker down.
    try:
        await _run_job_async_inner(job, source=source)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        logger.exception(
            "chat turn crashed (conversation=%s); suppressed to protect the worker",
            job.get("conversation_id", "?"),
        )
        await _record_abandoned_turn(job, exc=exc)


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
            # Passing the conversation binds retrieval to the Page's assigned
            # Projects: a Page mapped to one Project must not answer from
            # another's catalog. Zalo conversations stay deployment-wide.
            deps = await build_deps(
                db,
                session_factory=worker_session_factory(),
                conversation_id=state.conversation_id,
            )
            deps.persist = _enqueue_persist  # wire candidate extraction on SENT
            # build_deps is done — run_turn's heartbeat will take over now.
            if bridge_task is not None:
                bridge_task.cancel()
            started_at = _now()
            try:
                await run_turn(state, deps)
            except LLMThrottled as exc:
                # Every provider failed (quota/rate-limit/concurrency gate). The
                # failure is for engineers, not customers: an internal-capacity
                # apology reads as a broken bot and was never true (the cause is
                # quota, not traffic). Nothing is SENT — log the full diagnostics
                # and record the turn as SUPPRESSED so the lock clears, the
                # dashboard shows the degraded turn, and the conversation stays
                # available for the next inbound message.
                logger.error(
                    "llm_throttled: all LLM providers exhausted, no reply sent "
                    "conversation=%s trace=%s reason=%s",
                    job.get("conversation_id", "?"),
                    trace_id or "-",
                    exc,
                )
                try:
                    from app.graph.decision_trace import DecisionTraceBuilder
                    from app.services.conversation import ConversationService

                    svc = ConversationService(db)
                    conv = await svc.get(uuid.UUID(state.conversation_id))
                    if conv is not None:
                        await db.refresh(conv)
                        lock_owner = state.lock_owner or None
                        trace_sink = DecisionTraceBuilder()
                        trace_sink.record_decision("degradation_reason", "llm_throttled")
                        decision_trace = (
                            getattr(exc, "decision_trace", None) or trace_sink.snapshot_payload()
                        )
                        throttle_timings = _preamble_timings(
                            state, started_at, lane="agent", throttle=True
                        )
                        await svc.record_bot_outcome(
                            conv,
                            version_at_start=state.version_at_start,
                            reply="",  # nothing was sent — the audit row stays empty
                            started_at=started_at,
                            sent=False,
                            pending_message_id=state.pending_message_id,
                            stage_timings=throttle_timings,
                            lock_owner=lock_owner,
                            trace_id=state.trace_id or None,
                            decision_trace=decision_trace,
                        )
                except Exception:  # noqa: BLE001
                    logger.error("failed to record degraded turn outcome", exc_info=True)
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
