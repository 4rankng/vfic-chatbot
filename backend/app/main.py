"""VFIC API entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, bot_runs, conversations, dashboard, jobs, knowledge, leads, realtime, users, webhooks
from app.core.config import get_settings
from app.core.db import engine
from app.core.logging import setup_logging

settings = get_settings()
setup_logging()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("vfic backend starting env=%s", settings.app_env)
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
app.include_router(jobs.router, prefix=API_V1_PREFIX)
app.include_router(dashboard.router, prefix=API_V1_PREFIX)
app.include_router(realtime.router, prefix="/realtime")
app.include_router(webhooks.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": settings.app_env}
