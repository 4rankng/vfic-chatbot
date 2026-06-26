"""VFIC API entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, bot_runs, conversations, dashboard, jobs, knowledge, leads, personas, projects, realtime, users, webhooks
from app.core.config import get_settings
from app.core.db import engine
from app.core.logging import setup_logging

settings = get_settings()
setup_logging()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("vfic backend starting env=%s", settings.app_env)
    # Ensure the canonical 'vfic' project + a default persona exist (idempotent,
    # non-fatal). resolve_persona falls back to persona.md regardless.
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
