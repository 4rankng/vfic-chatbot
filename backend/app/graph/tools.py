"""Retrieval tools the agent may call:

  * search_user_memory  -> match_memories top-5 filtered by chat_id
  * search_knowledge    -> project-scoped semantic retrieval
  * search_bus_timetable-> complete structured bus route groups + stop times

Each takes an injected embedder + async db session, so they are testable
without an LLM. STRICT rule (from the agent prompt): advise only from returned data.

All SQL lives in ``app.services.retrieval.RetrievalRepository``; these functions own
the embedding (a graph-layer concern) + the Vietnamese formatting only.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from hashlib import sha256
from typing import Any

from app.core.cache import cache_get_json, cache_set_json, cache_version
from app.core.config import get_settings
from app.core.text import normalize_vietnamese_text
from app.core.vector import vec_literal
from app.graph.llm import Embedder
from app.graph.ports import RetrievalPort

logger = logging.getLogger(__name__)

_RECOMMEND_STOPWORDS = {
    "anh",
    "ban",
    "can",
    "cho",
    "co",
    "con",
    "cua",
    "duoc",
    "em",
    "goi",
    "hoi",
    "la",
    "lam",
    "minh",
    "mot",
    "muon",
    "nao",
    "toi",
    "ung",
    "viec",
    "voi",
}


def _cache_digest(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


async def _cached_embed(embedder: Embedder, query: str) -> list[float]:
    s = get_settings()
    if not s.rag_cache_enabled:
        return await embedder(query)
    query_hash = sha256(query.encode("utf-8")).hexdigest()
    provider = (s.embedding_provider or "openrouter").strip().lower()
    model = s.openrouter_embedding_model if provider == "openrouter" else s.gemini_embedding_model
    key = f"embed:{provider}:{model}:{s.embedding_dim}:{query_hash}"
    cached = await cache_get_json(key)
    if isinstance(cached, list) and cached:
        return [float(v) for v in cached]
    vector = await embedder(query)
    await cache_set_json(key, vector, s.embedding_cache_ttl_seconds)
    return vector


async def search_user_memory(
    retrieval: RetrievalPort, embedder: Embedder, chat_id: str, query: str, top_k: int = 5
) -> str:
    s = get_settings()
    memory_version = await cache_version(f"memory:{chat_id}") if s.rag_cache_enabled else "0"
    cache_key = f"rag:memory:{_cache_digest(chat_id, query, top_k, memory_version)}"
    if s.rag_cache_enabled:
        cached = await cache_get_json(cache_key)
        if isinstance(cached, str):
            return cached
    emb = vec_literal(await _cached_embed(embedder, query))
    rows = await retrieval.match_memories(
        emb, top_k, json.dumps({"chat_id": chat_id})
    )
    if not rows:
        result = "Không có thông tin ghi nhớ về người dùng này."
        await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
        return result
    logger.debug("search_user_memory: %d rows for chat %s", len(rows), chat_id)
    result = "\n".join(f"- {r.content} (sim={r.similarity:.2f})" for r in rows)
    if s.rag_cache_enabled:
        await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
    return result


def _format_knowledge_row(r) -> str:
    """Format a single retrieval row into the agent-readable citation string."""
    metadata = getattr(r, "metadata", None) or {}
    citation = metadata.get("citation") or {}
    document_meta = metadata.get("document_metadata") or {}
    chunk_meta = metadata.get("chunk_metadata") or {}
    source = citation.get("label") or document_meta.get("title") or "Nguồn kiến thức"
    anchor = citation.get("source_anchor") or metadata.get("source_anchor")
    source_file = getattr(r, "source_file", None)
    line_start = getattr(r, "line_start", None)
    line_end = getattr(r, "line_end", None)
    effective = document_meta.get("effective_from")
    if document_meta.get("effective_to"):
        effective = (
            f"{effective} đến {document_meta.get('effective_to')}"
            if effective
            else document_meta.get("effective_to")
        )
    route = chunk_meta.get("route_id")
    suffix = f" Nguồn: {source}"
    if source_file:
        suffix += f"; file: {source_file}"
    if line_start:
        suffix += f"; dòng: {line_start}"
        if line_end and line_end != line_start:
            suffix += f"-{line_end}"
    if anchor:
        suffix += f" ({anchor})"
    if effective:
        suffix += f"; hiệu lực: {effective}"
    if route:
        suffix += f"; route_id: {route}"
    # Prefer source_quote (precise evidence) over raw content;
    # append summary as supplementary context when available.
    quote = getattr(r, "source_quote", None)
    summary = getattr(r, "summary", None)
    parts: list[str] = []
    if quote:
        parts.append(str(quote))
    if summary:
        parts.append(f"Tóm tắt: {summary}")
    content = "\n".join(parts) if parts else str(r.content)
    return f"- {content}\n  {suffix}"


async def search_knowledge(
    retrieval: RetrievalPort,
    embedder: Embedder,
    query: str,
    project_slug: str | None = None,
    top_k: int = 25,
) -> str:
    """Project-scoped semantic search over usable knowledge (the `documents` VIEW).

    ``project_slug`` (from the master index) scopes retrieval to one product; omit it
    to search across all active projects. The agent is told to advise ONLY from this.

    FAQ-first pre-pass: canonical FAQ chunks (``category='faq'``) are retrieved with a
    higher similarity floor and prepended so the agent leads with curated answers.
    """
    repo = retrieval
    project_ids: list[str] | None = None
    if project_slug:
        pid = await repo.project_id_by_slug(project_slug, active_only=True)
        if pid is None:
            return "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
        project_ids = [str(pid)]
    s = get_settings()
    knowledge_version = await cache_version("knowledge") if s.rag_cache_enabled else "0"
    cache_key = (
        f"rag:knowledge:{_cache_digest(query, project_slug, top_k, project_ids, knowledge_version)}"
    )
    if s.rag_cache_enabled:
        cached = await cache_get_json(cache_key)
        if isinstance(cached, str):
            return cached

    emb = vec_literal(await _cached_embed(embedder, query))

    # FAQ-first pre-pass: prepend canonical FAQ answers when a strong match exists.
    faq_rows = await repo.match_faq(emb, top_k=3, project_ids=project_ids)
    faq_lines = [_format_knowledge_row(r) for r in faq_rows]
    faq_ids: set[str] = {str(getattr(r, "id", "")) for r in faq_rows}

    rows = await repo.match_documents(emb, top_k, "{}", project_ids=project_ids, query_text=query)
    if not rows and not faq_lines:
        result = "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
        await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
        return result
    logger.debug(
        "search_knowledge: %d rows (project=%s), %d faq rows",
        len(rows),
        project_slug,
        len(faq_lines),
    )
    lines: list[str] = []
    if faq_lines:
        lines.append("CÂU HỎI THƯỜNG GẶP (câu trả lời chuẩn):")
        lines.extend(faq_lines)
    for r in rows:
        # Skip FAQ chunks already prepended above to avoid double-counting.
        if faq_ids and str(getattr(r, "id", "")) in faq_ids:
            continue
        lines.append(_format_knowledge_row(r))
    result = "\n".join(lines)
    if s.rag_cache_enabled:
        await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
    return result


async def list_active_projects(retrieval: RetrievalPort) -> str:
    """Return the active-product catalog (name/slug/summary) for the agent."""
    rows = await retrieval.list_active_projects()
    if not rows:
        return "Hiện chưa có dự án/sản phẩm nào đang hoạt động."
    return "\n".join(
        f"- {r.slug} ({r.name})" + (f": {r.summary}" if r.summary else "") for r in rows
    )


def _recommend_terms(query: str) -> list[str]:
    normalized = normalize_vietnamese_text(query or "")
    terms = [
        term
        for term in normalized.split()
        if len(term) >= 3 and term not in _RECOMMEND_STOPWORDS
    ]
    seen: set[str] = set()
    return [term for term in terms if not (term in seen or seen.add(term))]


def _project_haystack(row) -> tuple[str, list[str], str]:
    card = getattr(row, "index_card", None) or {}
    roles = [str(role) for role in (card.get("key_roles") or []) if role]
    location = str(card.get("location") or "")
    summary = str(getattr(row, "summary", "") or "")
    parts = [
        str(getattr(row, "slug", "") or ""),
        str(getattr(row, "name", "") or ""),
        summary,
        location,
        *roles,
    ]
    return normalize_vietnamese_text(" ".join(parts)), roles, location


async def recommend_projects(
    retrieval: RetrievalPort,
    query: str,
    top_k: int = 3,
) -> str:
    """Rank active projects for a candidate query using existing catalog metadata.

    This is the first recommendation seam: deterministic, schema-free, and cheap.
    It does not replace the LLM; it gives the agent a small, grounded shortlist
    plus reasons before the agent calls project feature/detail tools.
    """
    try:
        k = max(1, min(int(top_k), 5))
    except (TypeError, ValueError):
        k = 3
    rows = await retrieval.active_projects_with_card()
    if not rows:
        return "Hiện chưa có dự án/sản phẩm nào đang hoạt động để gợi ý."

    terms = _recommend_terms(query)
    scored: list[tuple[float, list[str], object]] = []
    for row in rows:
        haystack, roles, location = _project_haystack(row)
        matched = [term for term in terms if term in haystack]
        score = len(matched) / max(len(terms), 1)
        reasons: list[str] = []
        if matched:
            reasons.append("khớp nhu cầu: " + ", ".join(matched[:5]))
        if location and any(term in normalize_vietnamese_text(location) for term in terms):
            reasons.append(f"địa điểm: {location}")
        role_hits = [
            role for role in roles
            if any(term in normalize_vietnamese_text(role) for term in terms)
        ]
        if role_hits:
            reasons.append("vị trí: " + ", ".join(role_hits[:3]))
        if not reasons:
            reasons.append("dự án đang hoạt động trong danh mục VFIC")
        scored.append((score, reasons, row))

    scored.sort(key=lambda item: (-item[0], str(getattr(item[2], "name", ""))))
    lines = [
        "GỢI Ý DỰ ÁN PHÙ HỢP (dựa trên danh mục đang hoạt động):",
    ]
    for score, reasons, row in scored[:k]:
        summary = str(getattr(row, "summary", "") or "").strip()
        slug = str(getattr(row, "slug", "") or "")
        name = str(getattr(row, "name", "") or slug)
        line = f"- {slug} ({name})"
        if summary:
            line += f": {summary}"
        line += f"; lý do: {'; '.join(reasons)}"
        if score > 0:
            line += f"; điểm khớp: {score:.2f}"
        lines.append(line)
    lines.append(
        "Sau khi chọn dự án/slug phù hợp, gọi get_product_features(project_slug) "
        "để kiểm tra lương, ca làm, KTX, xe đưa đón và hồ sơ trước khi tư vấn."
    )
    return "\n".join(lines)


async def search_bus_timetable(
    retrieval: RetrievalPort, company: str, question: str, limit: int = 50
) -> str:
    repo = retrieval
    rows = await repo.search_bus_timetable(company, question, limit)
    if not rows and company.strip():
        rows = await repo.search_bus_timetable("", question, limit)
    if not rows:
        logger.debug("search_bus_timetable: no rows for company=%s", company)
        return "Không tìm thấy lịch xe phù hợp."
    logger.debug("search_bus_timetable: %d rows for company=%s", len(rows), company)
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


async def get_product_features(retrieval: RetrievalPort, project_slug: str) -> str:
    """Return the project's active structured worker product features (catalog order).

    No embeddings — pure SQL over ``job_feature_values``. Precedent: ``search_bus_timetable``
    (structured, non-RAG data reaching the agent). The agent is told to advise ONLY from
    this and to answer "chưa ghi rõ" for missing features rather than invent.
    """
    repo = retrieval
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


async def recommend_jobs(
    retrieval: RetrievalPort,
    chat_id: str,
    *,
    top_k: int = 3,
    province: str | None = None,
) -> str:
    """Structured Job↔Lead recommendation (Phase 2).

    Two-stage ranker over the ``jobs`` table using the candidate's lead profile
    (desired_job, salary band, location, experience). Each result carries
    concrete matched reasons so the agent can ground its prose, then call
    ``get_product_features`` for the chosen project's detail.
    """
    s = get_settings()
    k = max(1, min(int(top_k or s.rec_top_k), 10))
    try:
        scored = await retrieval.match_jobs_for_lead(chat_id, top_k=k, province=province)
    except Exception:
        logger.warning("recommend_jobs failed for chat_id=%s", chat_id, exc_info=True)
        scored = []
    if not scored:
        return (
            "Chưa có thông tin hồ sơ (lương mong muốn, khu vực, vị trí) để gợi ý việc "
            "phù hợp, hoặc chưa có việc làm ACTIVE khớp. Hãy hỏi ứng viên thêm về khu "
            "vực / lương mong muốn, hoặc dùng recommend_projects để gợi ý theo dự án."
        )
    lines = ["GỢI Ý VIỆC LÀM PHÙ HỢP (dựa trên hồ sơ ứng viên):"]
    for item in scored:
        job = item.job
        sal = ""
        if job.salary_min and job.salary_max:
            sal = f"; lương {job.salary_min // 1_000_000}-{job.salary_max // 1_000_000} triệu"
        loc = f"; địa điểm: {job.province}" if job.province else ""
        lines.append(
            f"- {job.title} (id={job.id}){sal}{loc}; "
            f"lý do: {', '.join(item.reasons)}; điểm phù hợp: {item.score:.2f}"
        )
    lines.append(
        "QUY TẮC: chỉ tư vấn việc làm có trong danh sách trên. Với mỗi việc, "
        "nếu cần chi tiết lương/ca/KTX thì gọi get_product_features(project_slug). "
        "Tuyệt đối không bịa thông tin việc làm."
    )
    return "\n".join(lines)


TOOLS_REGISTRY = {
    "search_user_memory": search_user_memory,
    "search_knowledge": search_knowledge,
    "list_active_projects": list_active_projects,
    "recommend_projects": recommend_projects,
    "recommend_jobs": recommend_jobs,
    "search_bus_timetable": search_bus_timetable,
    "get_product_features": get_product_features,
}
