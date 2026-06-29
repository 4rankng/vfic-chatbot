"""Shared graph types: the BotRunState payload + the GraphDeps injection container.

Holds NO imports from ``runner`` / ``clients`` / ``factories`` / ``llm_real``, so it sits at
the bottom of the graph dependency graph. This is what breaks the old
``llm_real`` <-> ``runner`` import cycle: both ``factories.build_deps`` and ``runner`` import
``GraphDeps`` from here, never from each other.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.graph.llm import AgentModel, Embedder, SafetyModel
from app.services.zalo_bot_service import ZaloBotSender

# TYPE_CHECKING avoids pulling asyncpg into the runtime import path; the
# annotation is stringified by ``from __future__ import annotations`` anyway,
# but the explicit guard keeps linters/mypy happy without the import cost.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class BotRunState:
    conversation_id: str
    version_at_start: int
    user_text: str
    user_name: str = ""
    attempt: int = 0
    reply: str = ""


@dataclass
class GraphDeps:
    db: AsyncSession  # injected at runtime; AsyncSession only for type-checking
    agent: AgentModel
    safety: SafetyModel
    embedder: Embedder
    zalo: ZaloBotSender
    # Fire-and-forget lead/memory extraction after a SENT reply (port of the n8n
    # Persist Lead / Persist Memories nodes). None in tests -> persistence is skipped.
    persist: Callable[[dict], None] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _speaker(msg) -> str:
    """Map ``Message.sender`` to a Vietnamese label.

    Shared by both ``runner.py`` (reactive turns) and ``proactive.py``
    (proactive nudges) to avoid drift between identical label maps.
    """
    from app.models.conversation import MessageSender

    if msg.sender == MessageSender.WORKER:
        return "Ứng viên"
    if msg.sender == MessageSender.BOT:
        return "Bot"
    if msg.sender == MessageSender.RECRUITER:
        return "Nhân viên"
    return "Hệ thống"
