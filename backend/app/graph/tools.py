"""The 3 retrieval tools the agent may call (port of the n8n vector/postgres tools):

  * search_user_memory  -> match_memories top-5 filtered by chat_id
  * search_jobs         -> match_documents top-25 (over the `documents` VIEW)
  * search_bus_timetable-> SELECT * FROM search_bus_timetable('vfic', ...)

Each takes an injected embedder (Gemini) + async db session, so they are testable
without an LLM. STRICT rule (from the agent prompt): advise only from returned data.

All SQL lives in ``app.services.retrieval.RetrievalRepository``; these functions own
the embedding (a graph-layer concern) + the Vietnamese formatting only.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector import vec_literal
from app.graph.llm import Embedder
from app.services.retrieval import RetrievalRepository


async def search_user_memory(
    db: AsyncSession, embedder: Embedder, chat_id: str, query: str, top_k: int = 5
) -> str:
    emb = vec_literal(await embedder(query))
    rows = await RetrievalRepository(db).match_memories(
        emb, top_k, json.dumps({"chat_id": chat_id})
    )
    if not rows:
        return "Không có thông tin ghi nhớ về người dùng này."
    return "\n".join(f"- {r.content} (sim={r.similarity:.2f})" for r in rows)


async def search_knowledge(
    db: AsyncSession, embedder: Embedder, query: str, project_slug: str | None = None, top_k: int = 25
) -> str:
    """Project-scoped semantic search over usable knowledge (the `documents` VIEW).

    ``project_slug`` (from the master index) scopes retrieval to one product; omit it
    to search across all active projects. The agent is told to advise ONLY from this.
    """
    repo = RetrievalRepository(db)
    project_ids: list[str] | None = None
    if project_slug:
        pid = await repo.project_id_by_slug(project_slug, active_only=True)
        if pid is None:
            return "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
        project_ids = [str(pid)]
    emb = vec_literal(await embedder(query))
    rows = await repo.match_documents(emb, top_k, "{}", project_ids=project_ids)
    if not rows:
        return "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
    lines: list[str] = []
    for r in rows:
        metadata = getattr(r, "metadata", None) or {}
        citation = metadata.get("citation") or {}
        document_meta = metadata.get("document_metadata") or {}
        chunk_meta = metadata.get("chunk_metadata") or {}
        source = citation.get("label") or document_meta.get("title") or "Nguồn kiến thức"
        anchor = citation.get("source_anchor") or metadata.get("source_anchor")
        effective = document_meta.get("effective_from")
        if document_meta.get("effective_to"):
            effective = f"{effective} đến {document_meta.get('effective_to')}" if effective else document_meta.get("effective_to")
        route = chunk_meta.get("route_id")
        suffix = f" Nguồn: {source}"
        if anchor:
            suffix += f" ({anchor})"
        if effective:
            suffix += f"; hiệu lực: {effective}"
        if route:
            suffix += f"; route_id: {route}"
        lines.append(f"- {str(r.content)}\n  {suffix}")
    return "\n".join(lines)


async def search_jobs(
    db: AsyncSession, embedder: Embedder, query: str, top_k: int = 25
) -> str:
    """Back-compat unscoped search (delegates to search_knowledge)."""
    return await search_knowledge(db, embedder, query, top_k=top_k)


async def list_active_projects(db: AsyncSession) -> str:
    """Return the active-product catalog (name/slug/summary) for the agent."""
    rows = await RetrievalRepository(db).list_active_projects()
    if not rows:
        return "Hiện chưa có dự án/sản phẩm nào đang hoạt động."
    return "\n".join(
        f"- {r.slug} ({r.name})" + (f": {r.summary}" if r.summary else "") for r in rows
    )


async def search_bus_timetable(
    db: AsyncSession, company: str, question: str, limit: int = 50
) -> str:
    repo = RetrievalRepository(db)
    rows = await repo.search_bus_timetable(company, question, limit)
    if not rows and company.strip():
        rows = await repo.search_bus_timetable("", question, limit)
    if not rows:
        return "Không tìm thấy lịch xe phù hợp."
    # Repository retrieval completes each matched route before formatting. Keep
    # every returned stop/time visible so the LLM can answer at Agent X detail.
    groups: OrderedDict[tuple, list[tuple[str, str]]] = OrderedDict()
    for r in rows:
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
        parts = [f"{s}: {t}" if t else f"{s}: chưa có giờ trong nguồn" for s, t in stops if s]
        lines.append(
            f"- {company_name} • Tuyến {route} ({shift}/{direction}) đầy đủ điểm dừng: "
            + "; ".join(parts)
        )
    return "\n".join(lines)


async def get_product_features(db: AsyncSession, project_slug: str) -> str:
    """Return the project's active structured worker product features (catalog order).

    No embeddings — pure SQL over ``job_feature_values``. Precedent: ``search_bus_timetable``
    (structured, non-RAG data reaching the agent). The agent is told to advise ONLY from
    this and to answer "chưa ghi rõ" for missing features rather than invent.
    """
    repo = RetrievalRepository(db)
    pid = await repo.project_id_by_slug(project_slug)
    if pid is None:
        return f"Không tìm thấy dự án/sản phẩm với slug '{project_slug}'."
    rows = await repo.job_features_for_project(pid)
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
