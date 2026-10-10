"""VFIC API entrypoint."""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    auth,
    conversations,
    dashboard,
    integrations,
    installation,
    jobs,
    knowledge,
    knowledge_bases,
    leads,
    notifications,
    performance,
    projects,
    users,
    webhooks,
)
from app.core.config import get_settings
from app.workers.scheduler_utils import register_unique_cron_tick, register_unique_tick
from app.core.db import engine
from app.core.errors import register_domain_exception_handlers
from app.core.logging import request_id_ctx, setup_logging

settings = get_settings()
setup_logging()
logger = logging.getLogger("app")


async def _shutdown_web_resources() -> None:
    from app.core.http import aclose_all
    from app.graph.factories import aclose_client_cache
    from app.workers.chatbot_worker import drain_direct_chat_turns

    cancellation: asyncio.CancelledError | None = None
    for resource_name, cleanup in (
        ("direct chat turns", drain_direct_chat_turns),
        ("database engine", engine.dispose),
        ("LLM clients", aclose_client_cache),
        ("HTTP clients", aclose_all),
    ):
        cleanup_task = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
            logger.warning("web shutdown cleanup cancelled resource=%s", resource_name)
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - still close remaining resources
                logger.warning(
                    "web shutdown cleanup failed resource=%s",
                    resource_name,
                    exc_info=True,
                )
        except Exception:  # noqa: BLE001 - close remaining independent resources
            logger.warning(
                "web shutdown cleanup failed resource=%s",
                resource_name,
                exc_info=True,
            )
    logger.info("vfic backend stopped")
    if cancellation is not None:
        raise cancellation


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("vfic backend starting env=%s", settings.app_env)
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY is unset — password-reset emails will fail silently")
    # Register the periodic ticks in rq-scheduler. Each is registered through
    # register_unique_tick so exactly ONE recurring job exists per tick — earlier
    # boots stacked random-id duplicates that over-fired both ticks ~12x.
    try:
        from rq_scheduler import Scheduler

        from app.core.redis import get_redis_sync
        from app.workers.email_digest_worker import run_email_digest_tick
        from app.workers.outbound_dispatch_worker import run_outbound_dispatch_tick
        from app.workers.reconcile_worker import run_reconcile_tick

        # The proactive follow-up tick and its `followup` queue were removed
        # (2026-10-04). Reconcile sweep + outbound dispatch stay on `maintenance`.
        maintenance_sched = Scheduler(connection=get_redis_sync(), queue_name="maintenance")
        try:
            register_unique_tick(
                maintenance_sched, run_reconcile_tick, settings.reconcile_interval_seconds
            )
            logger.info(
                "reconcile sweep tick registered: interval=%ds queue=maintenance",
                settings.reconcile_interval_seconds,
            )
        except Exception:  # noqa: BLE001
            logger.exception("reconcile scheduler registration failed (non-fatal)")
        try:
            register_unique_tick(
                maintenance_sched, run_outbound_dispatch_tick, settings.reconcile_interval_seconds
            )
            logger.info(
                "outbound dispatcher tick registered: interval=%ds queue=maintenance",
                settings.reconcile_interval_seconds,
            )
        except Exception:  # noqa: BLE001
            logger.exception("outbound dispatcher scheduler registration failed (non-fatal)")
        try:
            from app.workers.knowledge_recovery_worker import run_knowledge_recovery_tick

            register_unique_tick(
                maintenance_sched,
                run_knowledge_recovery_tick,
                settings.knowledge_recovery_interval_seconds,
            )
            logger.info(
                "knowledge recovery tick registered: interval=%ds queue=maintenance",
                settings.knowledge_recovery_interval_seconds,
            )
        except Exception:  # noqa: BLE001
            logger.exception("knowledge recovery scheduler registration failed (non-fatal)")
        try:
            register_unique_cron_tick(
                maintenance_sched,
                run_email_digest_tick,
                settings.email_digest_tick_cron,
                job_timeout_seconds=settings.email_digest_job_timeout_seconds,
            )
            logger.info(
                "email digest tick registered: cron=%s queue=maintenance",
                settings.email_digest_tick_cron,
            )
        except Exception:  # noqa: BLE001
            logger.exception("email digest scheduler registration failed (non-fatal)")
    except Exception:  # noqa: BLE001
        logger.exception("rq-scheduler setup failed (non-fatal)")

    try:
        yield
    finally:
        # Direct turns finish before their DB/provider resources. Every cleanup
        # remains independent so one close failure cannot strand another pool.
        await _shutdown_web_resources()


app = FastAPI(title="VFIC API", version="0.1.0", lifespan=lifespan)
register_domain_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Host allowlist (SEC-06): a request whose Host header is not one of the
# deployment's hostnames never reaches a handler, so a Host-spoofing /
# DNS-rebinding request cannot make an endpoint echo attacker-controlled
# absolute URLs. The list is ALLOWED_HOSTS (comma-separated bare hostnames);
# localhost/127.0.0.1 stay allowed for the container healthchecks and local dev.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)

API_V1_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_V1_PREFIX)
app.include_router(users.router, prefix=API_V1_PREFIX)
app.include_router(conversations.router, prefix=API_V1_PREFIX)
app.include_router(leads.router, prefix=API_V1_PREFIX)
app.include_router(knowledge.router, prefix=API_V1_PREFIX)
app.include_router(knowledge_bases.router, prefix=API_V1_PREFIX)
app.include_router(projects.router, prefix=API_V1_PREFIX)
app.include_router(jobs.router, prefix=API_V1_PREFIX)
app.include_router(dashboard.router, prefix=API_V1_PREFIX)
app.include_router(performance.router, prefix=API_V1_PREFIX)
app.include_router(notifications.router, prefix=API_V1_PREFIX)
app.include_router(integrations.router, prefix=API_V1_PREFIX)
app.include_router(installation.router, prefix=API_V1_PREFIX)
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
        from app.core.redis import get_redis_sync, sync_value

        conn = get_redis_sync()
        queues = {}
        for name in (
            "webhook_high",
            "recovery",
            "persistence_low",
            "category",
            "ingest",
            "maintenance",
        ):
            queues[name] = Queue(name, connection=conn).count  # O(1) Redis LLEN
        queues["workers"] = Worker.count(connection=conn)  # O(1) Redis SCARD
        # Reconcile canary counters (written by reconcile_worker via Redis INCR/SET).
        for key in (
            "reconcile_re_enqueues_total",
            "reconcile_stale_pending_total",
            "reconcile_unanswered_inbound_total",
            "reconcile_superseded_inbound_total",
            "reconcile_skipped_locked_total",
            "reconcile_enqueue_failed_total",
            "reconcile_unknown_send_outcome",
            "reconcile_stale_lock_broken",
            "reconcile_unanswered_gauge",
        ):
            queues[key] = int(sync_value(conn.get(key)) or 0)
        return queues

    return await asyncio.to_thread(_collect)


@app.get("/health/queue")
async def health_queue() -> dict:
    """Chat-path observability: queue depth, LLM latency, 429 count, worker saturation.

    Unauthenticated (internal ops endpoint, same trust level as /health). The
    snapshot lives in app.core.ops_health so /admin/performance reuses the same
    live tiles without duplicating the Redis/RQ reads.
    """
    from app.core.ops_health import collect_queue_health

    return await asyncio.to_thread(collect_queue_health)


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
# becomes the fallback for every non-Socket.IO request, and its lifespan is
# forwarded by the ASGIApp. Importing the server here (after
# all routers/middleware are registered) keeps the construction cost out of test
# collection's import path.
import socketio  # noqa: E402

from app.realtime.socketio import sio as _vfic_sio  # noqa: E402

app = socketio.ASGIApp(_vfic_sio, other_asgi_app=app)
