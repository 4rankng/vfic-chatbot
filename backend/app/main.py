"""VFIC API entrypoint."""
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, bot_runs, conversations, dashboard, jobs, knowledge, leads, personas, projects, realtime, users, webhooks
from app.core.config import get_settings
from app.core.db import engine
from app.core.logging import request_id_ctx, setup_logging

settings = get_settings()
setup_logging()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("vfic backend starting env=%s", settings.app_env)
    # Ensure a default persona exists (idempotent, non-fatal). resolve_persona falls
    # back to persona.md regardless.
    try:
        from app.core.db import async_session
        from app.services.seeder import ensure_defaults

        async with async_session() as db:
            await ensure_defaults(db)
    except Exception:  # noqa: BLE001
        logger.exception("startup seeder failed (non-fatal)")
    yield
    await engine.dispose()
    logger.info("vfic backend stopped")


app = FastAPI(title="VFIC API", version="0.1.0", lifespan=lifespan)

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
        for name in ("webhook_high", "persistence_low", "ingest"):
            queues[name] = Queue(name, connection=conn).count  # O(1) Redis LLEN
        queues["workers"] = Worker.count(connection=conn)  # O(1) Redis SCARD
        return queues

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
