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
    db: object  # AsyncSession
    agent: AgentModel
    safety: SafetyModel
    embedder: Embedder
    zalo: ZaloBotSender
    # Fire-and-forget lead/memory extraction after a SENT reply (port of the n8n
    # Persist Lead / Persist Memories nodes). None in tests -> persistence is skipped.
    persist: Callable[[dict], None] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)
