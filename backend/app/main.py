"""VFIC API entrypoint."""
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, bot_runs, conversations, dashboard, jobs, knowledge, leads, personas, projects, realtime, users, webhooks
from app.core.config import PROACTIVE_TICK_INTERVAL_SECONDS, get_settings
from app.core.db import engine
from app.core.errors import register_domain_exception_handlers
from app.core.logging import request_id_ctx, setup_logging

settings = get_settings()
setup_logging()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("vfic backend starting env=%s", settings.app_env)
    if not settings.resend_api_key:
        logger.warning(
            "RESEND_API_KEY is unset — password-reset emails will fail silently"
        )
    # Ensure a default persona exists (idempotent, non-fatal). resolve_persona falls
    # back to persona.md regardless.
    try:
        from app.core.db import async_session
        from app.services.seeder import ensure_defaults

        async with async_session() as db:
            await ensure_defaults(db)
    except Exception:  # noqa: BLE001
        logger.exception("startup seeder failed (non-fatal)")

    # Register proactive follow-up tick in rq-scheduler (idempotent — re-registering
    # on every boot is safe and ensures the schedule survives scheduler restarts).
    try:
        from datetime import datetime, timezone

        from rq_scheduler import Scheduler

        from app.core.redis import get_redis_sync
        from app.workers.followup_worker import run_proactive_followup_tick

        conn = get_redis_sync()
        sched = Scheduler(connection=conn, queue_name="followup")
        # cancel_any is False by default in schedule(); the repeatable job id is
        # derived from func.__name__ so re-registration is idempotent.
        sched.schedule(
            scheduled_time=datetime.now(timezone.utc),
            func=run_proactive_followup_tick,
            interval=PROACTIVE_TICK_INTERVAL_SECONDS,
            repeat=None,  # repeat indefinitely
        )
        logger.info("proactive follow-up tick registered: interval=%ds", PROACTIVE_TICK_INTERVAL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.exception("proactive scheduler registration failed (non-fatal)")

    # Register reconcile sweep tick (recovers lost bot turns after crash/restart).
    try:
        from app.workers.reconcile_worker import run_reconcile_tick

        sched.schedule(
            scheduled_time=datetime.now(timezone.utc),
            func=run_reconcile_tick,
            interval=settings.reconcile_interval_seconds,
            repeat=None,
        )
        logger.info("reconcile sweep tick registered: interval=%ds", settings.reconcile_interval_seconds)
    except Exception:  # noqa: BLE001
        logger.exception("reconcile scheduler registration failed (non-fatal)")

    yield
    await engine.dispose()
    logger.info("vfic backend stopped")


app = FastAPI(title="VFIC API", version="0.1.0", lifespan=lifespan)
register_domain_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_V1_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_V1_PREFIX)
app.include_router(users.router, prefix=API_V1_PREFIX)
app.include_router(conversations.router, prefix=API_V1_PREFIX)
app.include_router(leads.router, prefix=API_V1_PREFIX)
app.include_router(bot_runs.router, prefix=API_V1_PREFIX)
app.include_router(knowledge.router, prefix=API_V1_PREFIX)
app.include_router(projects.router, prefix=API_V1_PREFIX)
app.include_router(personas.router, prefix=API_V1_PREFIX)
app.include_router(jobs.router, prefix=API_V1_PREFIX)
app.include_router(dashboard.router, prefix=API_V1_PREFIX)
app.include_router(realtime.router, prefix="/realtime")
app.include_router(webhooks.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": settings.app_env}


@app.get("/metrics")
async def metrics() -> dict:
    """RQ queue depths + worker count — the signal for scaling worker-chatbot replicas.

    Unauthenticated (internal ops endpoint, same trust level as /health).
    """
    def _collect() -> dict:
        from rq import Queue, Worker
        from app.core.redis import get_redis_sync

        conn = get_redis_sync()
        queues = {}
        for name in ("webhook_high", "persistence_low", "ingest", "followup"):
            queues[name] = Queue(name, connection=conn).count  # O(1) Redis LLEN
        queues["workers"] = Worker.count(connection=conn)  # O(1) Redis SCARD
        # Reconcile canary counters (written by reconcile_worker via Redis INCR/SET).
        for key in (
            "reconcile_re_enqueues_total",
            "reconcile_stale_pending_total",
            "reconcile_unanswered_inbound_total",
            "reconcile_skipped_locked_total",
            "reconcile_enqueue_failed_total",
            "reconcile_unanswered_gauge",
        ):
            queues[key] = int(conn.get(key) or 0)
        return queues

    return await asyncio.to_thread(_collect)


@app.get("/health/queue")
async def health_queue() -> dict:
    """Chat-path observability: queue depth, LLM latency, 429 count, worker saturation.

    Unauthenticated (internal ops endpoint, same trust level as /health).
    """
    def _collect() -> dict:
        from rq import Queue, Worker

        from app.core.redis import get_redis_sync
        from app.graph.clients import _RKEY_429, _RKEY_INVOKE_COUNT, _RKEY_INVOKE_MS

        conn = get_redis_sync()
        qd = Queue("webhook_high", connection=conn).count
        total_w = Worker.count(connection=conn)
        busy_w = sum(1 for w in (Worker.all(connection=conn) or []) if w.get_current_job() is not None)

        # LLM metrics from Redis counters (best-effort, may be missing if no turns yet).
        invoke_count = int(conn.get(_RKEY_INVOKE_COUNT) or 0)
        invoke_total_ms = int(conn.get(_RKEY_INVOKE_MS) or 0)
        avg_latency_ms = round(invoke_total_ms / invoke_count) if invoke_count else 0
        minimax_429s_1m = int(conn.get(_RKEY_429) or 0)

        return {
            "queue_depth": qd,
            "busy_workers": busy_w,
            "total_workers": total_w,
            "llm_avg_latency_ms": avg_latency_ms,
            "llm_invokes_last_2m": invoke_count,
            "minimax_429s_last_1m": minimax_429s_1m,
        }

    return await asyncio.to_thread(_collect)


@app.middleware("http")
async def request_id_middleware(request, call_next):
    """Stamp every request with a correlation id (echoed back as X-Request-Id)
    so a failure traces across logs and downstream Zalo/RQ calls."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_ctx.set(rid)
    try:
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response
    finally:
        request_id_ctx.reset(token)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """Catch-all: log with request_id and return a consistent Vietnamese 500
    instead of a bare English 'Internal Server Error'. Keeps the {detail} shape
    the frontend already parses. HTTPException has its own handler, so genuine
    business errors (Vietnamese detail, intended status) are unaffected."""
    logger.exception("unhandled error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Đã có lỗi xảy ra, vui lòng thử lại sau."},
    )


# Socket.IO realtime: mount the AsyncServer at the ASGI root so /socket.io/ is
# served alongside the REST API (Caddy forwards WebSocket upgrades by default,
# so wss://<origin>/socket.io/ works with no edge change). The FastAPI app
# becomes the fallback for every non-Socket.IO request, and its lifespan
# (startup seeder) is forwarded by the ASGIApp. Importing the server here (after
# all routers/middleware are registered) keeps the construction cost out of test
# collection's import path.
import socketio  # noqa: E402

from app.realtime.socketio import sio as _vfic_sio  # noqa: E402

app = socketio.ASGIApp(_vfic_sio, other_asgi_app=app)
