"""Project-catalog tools: catalog listing, project recommendation, structured reads.

Everything that reads the active project catalog or a single project's
structured data — without embeddings — lives here: the catalog listing, the
deterministic project recommender, bus timetables, and product features.
All SQL lives in ``app.services.retrieval.RetrievalRepository`` (behind the
``GraphRetrievalPort``); these functions own the Vietnamese formatting only.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from app.core.cache import cache_get_json, cache_set_json, cache_version
from app.core.config import get_settings
from app.graph.ports import GraphRetrievalPort
from app.graph.tools._shared import _cache_digest
from app.shared.domain.text import normalize_vietnamese_text

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
    "dung",
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
    "tuyen",
    "ung",
    "viec",
    "voi",
}


def _recommend_terms(query: str) -> list[str]:
    normalized = normalize_vietnamese_text(query or "")
    terms = [
        term for term in normalized.split() if len(term) >= 3 and term not in _RECOMMEND_STOPWORDS
    ]
    seen: set[str] = set()
    return [term for term in terms if not (term in seen or seen.add(term))]


def _project_haystack(row) -> tuple[str, list[str], str]:
    card = getattr(row, "index_card", None) or {}
    roles = [str(role) for role in (card.get("roles") or card.get("key_roles") or []) if role]
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
    retrieval: GraphRetrievalPort,
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
    if not terms:
        return "Bạn cho tôi biết vị trí hoặc khu vực mong muốn để gợi ý dự án phù hợp."
    scored: list[tuple[float, list[str], object]] = []
    for row in rows:
        haystack, roles, location = _project_haystack(row)
        haystack_tokens = set(haystack.split())
        matched = [term for term in terms if term in haystack_tokens]
        score = len(matched) / max(len(terms), 1)
        reasons: list[str] = []
        if matched:
            reasons.append("khớp nhu cầu: " + ", ".join(matched[:5]))
        location_tokens = set(normalize_vietnamese_text(location).split())
        if location and any(term in location_tokens for term in terms):
            reasons.append(f"địa điểm: {location}")
        role_hits = [
            role
            for role in roles
            if any(term in set(normalize_vietnamese_text(role).split()) for term in terms)
        ]
        if role_hits:
            reasons.append("vị trí: " + ", ".join(role_hits[:3]))
        if score > 0:
            scored.append((score, reasons, row))

    if not scored:
        return (
            "Không có dự án trong danh mục phù hợp với yêu cầu này. "
            "Danh mục dự án không phải bằng chứng rằng vị trí đang tuyển."
        )

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
        line += f"; điểm khớp: {score:.2f}"
        lines.append(line)
    lines.append(
        "Sau khi chọn dự án/slug phù hợp, gọi get_product_features(project_slug) "
        "để kiểm tra lương, ca làm, KTX, xe đưa đón và hồ sơ trước khi tư vấn."
    )
    return "\n".join(lines)


async def list_active_projects(retrieval: GraphRetrievalPort) -> str:
    """Return the active-product catalog (name/slug/summary) for the agent."""
    rows = await retrieval.list_active_projects()
    if not rows:
        return "Hiện chưa có dự án/sản phẩm nào đang hoạt động."
    return "\n".join(
        f"- {r.slug} ({r.name})" + (f": {r.summary}" if r.summary else "") for r in rows
    )


async def search_bus_timetable(
    retrieval: GraphRetrievalPort,
    company: str,
    question: str,
    limit: int = 50,
    *,
    strict_company: bool = False,
) -> str:
    s = get_settings()
    # Bus timetables change rarely; cache the formatted result for the TTL so
    # repeated timetable questions (a common pattern) skip the DB query.
    cache_key = f"rag:bus_timetable:{_cache_digest(company, question, limit, strict_company)}"
    if s.rag_cache_enabled:
        cached = await cache_get_json(cache_key)
        if isinstance(cached, str):
            return cached
    repo = retrieval
    rows = await repo.search_bus_timetable(company, question, limit)
    if not rows and company.strip() and not strict_company:
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
    result = "\n".join(lines)
    if s.rag_cache_enabled:
        await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
    return result


async def get_product_features(
    retrieval: GraphRetrievalPort, project_slug: str
) -> str:
    """Return the project's active structured worker product features (catalog order).

    No embeddings — pure SQL over ``job_feature_values``. Precedent: ``search_bus_timetable``
    (structured, non-RAG data reaching the agent). The agent is told to advise ONLY from
    this and to answer "chưa ghi rõ" for missing features rather than invent.
    """
    s = get_settings()
    # Product features change only when jobs are re-imported; cache the formatted
    # result keyed by the knowledge version so FAQ/project edits invalidate it.
    knowledge_version = await cache_version("knowledge") if s.rag_cache_enabled else "0"
    cache_key = f"rag:product_features:{_cache_digest(project_slug, knowledge_version)}"
    if s.rag_cache_enabled:
        cached = await cache_get_json(cache_key)
        if isinstance(cached, str):
            return cached
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
    result = "\n".join(lines)
    if s.rag_cache_enabled:
        await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
    return result
