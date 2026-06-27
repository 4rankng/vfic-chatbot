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


async def search_knowledge(
    db: AsyncSession, embedder: Embedder, query: str, project_slug: str | None = None, top_k: int = 25
) -> str:
    """Project-scoped semantic search over APPROVED knowledge (the `documents` VIEW).

    ``project_slug`` (from the master index) scopes retrieval to one product; omit it
    to search across all active projects. The agent is told to advise ONLY from this.
    """
    project_ids: list[str] | None = None
    if project_slug:
        pid_rows = (
            await db.execute(
                text("SELECT id FROM projects WHERE slug = :s AND is_active"), {"s": project_slug}
            )
        ).all()
        project_ids = [str(r[0]) for r in pid_rows] or None
    emb = vec_literal(await embedder(query))
    if project_ids:
        rows = (
            await db.execute(
                text(
                    "SELECT id, content, similarity FROM match_documents("
                    "CAST(:emb AS vector), :k, CAST(:filter AS jsonb), CAST(:pids AS uuid[]))"
                ),
                {"emb": emb, "k": top_k, "filter": "{}", "pids": project_ids},
            )
        ).all()
    else:
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
        return "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
    return "\n".join(f"- {str(r.content)[:300]}" for r in rows)


async def search_jobs(
    db: AsyncSession, embedder: Embedder, query: str, top_k: int = 25
) -> str:
    """Back-compat unscoped search (delegates to search_knowledge)."""
    return await search_knowledge(db, embedder, query, top_k=top_k)


async def list_active_projects(db: AsyncSession) -> str:
    """Return the active-product catalog (name/slug/summary) for the agent."""
    rows = (
        await db.execute(
            text("SELECT name, slug, summary FROM projects WHERE is_active ORDER BY name")
        )
    ).all()
    if not rows:
        return "Hiện chưa có dự án/sản phẩm nào đang hoạt động."
    return "\n".join(
        f"- {r.slug} ({r.name})" + (f": {r.summary}" if r.summary else "") for r in rows
    )


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


async def get_product_features(db: AsyncSession, project_slug: str) -> str:
    """Return the project's 16 structured worker product features (catalog order).

    No embeddings — pure SQL over ``job_feature_values``. Precedent: ``search_bus_timetable``
    (structured, non-RAG data reaching the agent). The agent is told to advise ONLY from
    this and to answer "chưa ghi rõ" for missing features rather than invent.
    """
    pid = (
        await db.execute(text("SELECT id FROM projects WHERE slug = :s"), {"s": project_slug})
    ).scalar_one_or_none()
    if pid is None:
        return f"Không tìm thấy dự án/sản phẩm với slug '{project_slug}'."
    rows = (
        await db.execute(
            text(
                "SELECT jfv.value_text, jfv.value_json, jfv.is_highlight, jfv.is_missing, "
                "       jfv.needs_clarification, jfv.evidence_text, "
                "       wfc.name_vi, wfc.feature_key "
                "FROM job_feature_values jfv "
                "JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id "
                "WHERE jfv.project_id = :pid "
                "ORDER BY jfv.display_priority ASC, wfc.default_importance_score DESC"
            ),
            {"pid": str(pid)},
        )
    ).all()
    if not rows:
        return (
            f"Chưa có đặc điểm sản phẩm cho dự án '{project_slug}' "
            "(cần tải tin tuyển dụng lên và trích xuất đặc điểm)."
        )
    lines: list[str] = [f"Đặc điểm sản phẩm — dự án '{project_slug}':"]
    for r in rows:
        if r.is_missing or r.needs_clarification:
            flag = " [CHƯA RÕ — trả lời là 'chưa ghi rõ', không bịa]"
        elif r.is_highlight:
            flag = " [NỔI BẬT]"
        else:
            flag = ""
        lines.append(f"- {r.name_vi}: {r.value_text}{flag}")
    lines.append(
        "QUY TẮC: chỉ tư vấn dựa trên dữ liệu trên. Với mục [CHƯA RÕ], "
        "trả lời 'tin tuyển dụng chưa ghi rõ', tuyệt đối không bịa."
    )
    return "\n".join(lines)


TOOLS_REGISTRY = {
    "search_user_memory": search_user_memory,
    "search_jobs": search_jobs,
    "search_knowledge": search_knowledge,
    "list_active_projects": list_active_projects,
    "search_bus_timetable": search_bus_timetable,
    "get_product_features": get_product_features,
}
