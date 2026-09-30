"""The canonical agent persona, frozen in code.

The personas admin page was removed on 2026-09-30; the bot's voice is no longer
operator-editable content. This module is the service-side entry point for the
default persona: the seed fixture writes it into the ``personas`` row and
``app.graph.prompts.AGENT_SYSTEM_PROMPT`` falls back to it when no DB row is
active. The body itself lives in the neutral ``app.prompts.vfic_persona`` layer
so the graph runtime can read it without importing this service module.
"""

from __future__ import annotations

from app.prompts.vfic_persona import DEFAULT_PERSONA_BODY_MD

__all__ = [
    "DEFAULT_PERSONA_BODY_MD",
    "DEFAULT_PERSONA_NAME",
    "DEFAULT_PERSONA_SLUG",
]

DEFAULT_PERSONA_NAME = "VFIC Bot mặc định"
DEFAULT_PERSONA_SLUG = "default-vfic"
