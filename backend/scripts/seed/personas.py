"""Persona fixture: the global default bot persona plus one inactive preset."""

from __future__ import annotations

from app.models.persona import Persona
from app.models.user import User
from app.services.personas.constant import (
    DEFAULT_PERSONA_BODY_MD,
    DEFAULT_PERSONA_NAME,
    DEFAULT_PERSONA_SLUG,
)

from .common import new_uuid


def make_personas(users: list[User]) -> list[Persona]:
    """Two global personas: exactly one active default, one inactive preset.

    The active default carries the canonical code constant verbatim — the
    personas admin page is gone, so seed and fallback must agree with
    ``app.graph.prompts.AGENT_SYSTEM_PROMPT``. Personas attach to a knowledge
    base (``knowledge_base_id``) and adapter-specific overrides live in
    ``adapter_persona_assignments``. Both seeded rows stay unattached so the
    global active persona is the resolved default.
    """
    return [
        Persona(
            id=new_uuid(),
            name=DEFAULT_PERSONA_NAME,
            slug=DEFAULT_PERSONA_SLUG,
            body_md=DEFAULT_PERSONA_BODY_MD,
            is_active=True,
            created_by=users[0].id,
        ),
        Persona(
            id=new_uuid(),
            name="LG Display tư vấn viên",
            slug="lg-display",
            body_md=(
                "# LG Display Tuyển dụng\n\n"
                "Bạn là tư vấn viên chuyên tuyển dụng cho nhà máy LG Display. "
                "Thông tin chi tiết về các nhà máy, lương thưởng, phúc lợi.\n\n"
                "## Yêu cầu\n"
                "- Chỉ tư vấn về LG Display\n"
                "- Dữ liệu bám sát bus timetable, lương, phúc lợi\n"
            ),
            is_active=False,
            created_by=users[0].id,
        ),
    ]
