"""The 3 retrieval tools the agent may call (port of the n8n vector/postgres tools):

  * search_user_memory  -> match_memories top-5 filtered by chat_id
  * search_jobs         -> match_documents top-25 (over the `documents` VIEW)
  * search_bus_timetable-> SELECT * FROM search_bus_timetable('vfic', ...)

Each takes an injected embedder (Gemini) + async db session, so they are testable
without an LLM. STRICT rule (from the agent prompt): advise only from returned data.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector import vec_literal
from app.graph.llm import Embedder


async def search_user_memory(
    db: AsyncSession, embedder: Embedder, chat_id: str, query: str, top_k: int = 5
) -> str:
    emb = vec_literal(await embedder(query))
    rows = (
        await db.execute(
            text(
                "SELECT content, similarity FROM match_memories("
                "CAST(:emb AS vector), :k, CAST(:filter AS jsonb))"
            ),
            {"emb": emb, "k": top_k, "filter": json.dumps({"chat_id": chat_id})},
        )
    ).all()
    if not rows:
        return "Không có thông tin ghi nhớ về người dùng này."
    return "\n".join(f"- {r.content} (sim={r.similarity:.2f})" for r in rows)


async def search_jobs(
    db: AsyncSession, embedder: Embedder, query: str, top_k: int = 25
) -> str:
    emb = vec_literal(await embedder(query))
    rows = (
        await db.execute(
            text(
                "SELECT id, content, similarity FROM match_documents("
                "CAST(:emb AS vector), :k, CAST(:filter AS jsonb))"
            ),
            {"emb": emb, "k": top_k, "filter": "{}"},
        )
    ).all()
    if not rows:
        return "Không tìm thấy công việc phù hợp trong cơ sở dữ liệu VFIC."
    return "\n".join(f"- {str(r.content)[:300]}" for r in rows)


async def search_bus_timetable(
    db: AsyncSession, company: str, question: str, limit: int = 20
) -> str:
    rows = (
        await db.execute(
            text("SELECT * FROM search_bus_timetable('vfic', :company, :question, NULL, NULL, :limit)"),
            {"company": company, "question": question, "limit": limit},
        )
    ).all()
    if not rows:
        return "Không tìm thấy lịch xe phù hợp."
    # The SQL fn returns one row per stop; group into one line per route and surface
    # scheduled_time (the actual answer to "mấy giờ"). The old formatter read a
    # non-existent `stops` column, dropped the time entirely, and fragmented a route
    # into N per-stop bullets.
    groups: OrderedDict[tuple, list[tuple[str, str]]] = OrderedDict()
    for r in rows[:limit]:
        m: dict[str, Any] = dict(r._mapping)
        key = (
            m.get("company_name") or "?",
            m.get("route_name") or m.get("route_variant") or "?",
            m.get("shift") or "?",
            m.get("direction") or "?",
        )
        stop = str(m.get("stop_name") or "").strip()
        when = str(m.get("scheduled_time") or "").strip()
        groups.setdefault(key, []).append((stop, when))
    lines: list[str] = []
    for (company_name, route, shift, direction), stops in groups.items():
        parts = [f"{s} {t}" if t else s for s, t in stops if s]
        lines.append(
            f"- {company_name} • {route} ({shift}/{direction}) các điểm đón: {', '.join(parts)}"
        )
    return "\n".join(lines)


TOOLS_REGISTRY = {
    "search_user_memory": search_user_memory,
    "search_jobs": search_jobs,
    "search_bus_timetable": search_bus_timetable,
}
