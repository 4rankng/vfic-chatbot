"""Runtime system-prompt assembly: active persona + master index of active products.

The persona (the bot's voice) is the active *global* persona's ``body_md`` (managed in
the admin UI), falling back to the committed ``persona.md`` when none is active so the
live bot never breaks. The "master index of active products" (user's routing model:
projects = products the candidate can choose from) is read from active ``projects`` and
appended to the prompt so the agent always knows the catalog + slugs, and scopes
``search_knowledge`` to the relevant project.

All DB lookups are best-effort: any failure collapses to ``AGENT_SYSTEM_PROMPT`` so a
persona/index hiccup can never break a chat turn.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.prompts import AGENT_SYSTEM_PROMPT

_INDEX_HEADER = "\n\n=== DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG ==="


async def resolve_persona(db: AsyncSession) -> str:
    """Return the active global persona body, or persona.md if none is active."""
    try:
        row = (
            await db.execute(
                text("SELECT body_md FROM personas WHERE is_active AND project_id IS NULL LIMIT 1")
            )
        ).first()
        if row is not None and (row.body_md or "").strip():
            return row.body_md.strip()
    except Exception:  # noqa: BLE001
        pass
    return AGENT_SYSTEM_PROMPT


async def active_projects_index(db: AsyncSession) -> str:
    """Compact catalog of active projects (the agent's master index). '' if none/err."""
    try:
        rows = (
            await db.execute(
                text("SELECT name, slug, summary, index_card FROM projects WHERE is_active ORDER BY name")
            )
        ).all()
    except Exception:  # noqa: BLE001
        return ""
    if not rows:
        return ""
    lines: list[str] = []
    for r in rows:
        card = r.index_card or {}
        roles = ", ".join(card.get("key_roles") or [])
        loc = card.get("location") or ""
        seg = f"- {r.slug} ({r.name})"
        if r.summary:
            seg += f": {r.summary}"
        if roles:
            seg += f"; vị trí: {roles}"
        if loc:
            seg += f"; địa điểm: {loc}"
        lines.append(seg)
    return (
        _INDEX_HEADER
        + "\n" + "\n".join(lines)
        + "\nKhi ứng viên quan tâm một dự án cụ thể, hãy gọi search_knowledge với project_slug"
          " tương ứng (slug ở trên). TUYỆT ĐỐI chỉ tư vấn bám sát dữ liệu trả về."
    )


async def build_system_prompt(db: AsyncSession) -> str:
    """Persona body + active-product index, with a hard fallback to persona.md."""
    try:
        persona = await resolve_persona(db)
        index = await active_projects_index(db)
        return persona + index
    except Exception:  # noqa: BLE001
        return AGENT_SYSTEM_PROMPT
