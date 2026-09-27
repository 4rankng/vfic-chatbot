"""Persona fixture: the global default bot persona plus one inactive preset."""

from __future__ import annotations

from app.models.persona import Persona
from app.models.user import User

from .common import new_uuid


def make_personas(users: list[User]) -> list[Persona]:
    """Two global personas: exactly one active default, one inactive preset.

    Personas are no longer project-scoped; they attach to a knowledge base
    (``knowledge_base_id``) and adapter-specific overrides live in
    ``adapter_persona_assignments``. Both seeded rows stay unattached so the
    global active persona is the resolved default.
    """
    return [
        Persona(
            id=new_uuid(),
            name="VFIC Bot mặc định",
            slug="default-vfic",
            body_md=(
                "# VFIC Tư vấn viên tuyển dụng\n\n"
                "Bạn là trợ lý tuyển dụng của VFIC. Hãy tư vấn cho ứng viên một cách "
                "chuyên nghiệp, thân thiện, bằng tiếng Việt.\n\n"
                "## Phong cách\n"
                "- Gọi ứng viên là 'bạn'\n"
                "- Trả lời ngắn gọn, rõ ràng\n"
                "- Luôn dựa trên dữ liệu thực tế từ hệ thống\n"
                "- Không đưa thông tin không có trong dữ liệu\n"
            ),
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
