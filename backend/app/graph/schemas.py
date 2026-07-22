"""OpenAI-compatible tool schemas + the tool-call dispatcher.

Co-located with the agent tools (``app.graph.tools``) the schemas describe. ``_dispatch_tool``
routes a named tool call to its function; used by ``MiniMaxAgent``'s tool loop in
``clients.py``.
"""

from __future__ import annotations

import logging

from app.graph.tools import (
    get_product_features,
    list_active_jobs,
    list_active_projects,
    recommend_jobs,
    recommend_projects,
    search_bus_timetable,
    search_knowledge,
    search_user_memory,
)

logger = logging.getLogger(__name__)

# OpenAI-compatible function schemas handed to MiniMax.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_user_memory",
            "description": "Tra cứu thông tin đã nhớ về người dùng (lịch sử chat).",
            "parameters": {
                "type": "object",
                "properties": {"chat_id": {"type": "string"}, "query": {"type": "string"}},
                "required": ["chat_id", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_active_jobs",
            "description": (
                "Liệt kê việc làm đang ACTIVE từ dữ liệu có cấu trúc. Dùng cho mọi câu hỏi "
                "về vị trí/công việc đang tuyển, kể cả yêu cầu liệt kê chung. Có thể truyền role, "
                "company và location đã được diễn giải từ lời ứng viên; không đưa câu hỏi hội thoại "
                "nguyên văn vào các bộ lọc. Chỉ tư vấn từ các trường tool trả về."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_slug": {
                        "type": "string",
                        "description": "Slug dự án để giới hạn việc làm; bắt buộc khi đã chọn dự án.",
                    },
                    "role": {
                        "type": "string",
                        "description": "Tên vị trí/vai trò cần tìm, không kèm lời hội thoại.",
                    },
                    "company": {
                        "type": "string",
                        "description": "Tên hoặc bí danh công ty/nhà máy/dự án.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Tỉnh, quận/huyện hoặc địa chỉ cần tìm.",
                    },
                    "top_k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Số việc tối đa cần trả về, mặc định 3.",
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["updated_at", "salary_desc", "salary_asc", "created_at"],
                        "description": (
                            "Thứ tự sắp xếp. salary_desc: lương từ cao xuống thấp (dùng khi ứng viên "
                            "hỏi việc lương cao / sắp xếp theo lương). salary_asc: từ thấp đến cao. "
                            "created_at: việc làm mới đăng gần nhất (dùng khi ứng viên hỏi 'gần nhất' "
                            "/ 'mới nhất'). Bỏ qua nếu ứng viên không yêu cầu sắp xếp."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_active_projects",
            "description": "Liệt kê các dự án/sản phẩm (nhà máy) đang hoạt động để tư vấn cho ứng viên.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Tìm thông tin kiến thức/tuyển dụng trong cơ sở dữ liệu. Truyền project_slug để giới hạn "
                "theo một dự án. Dùng bắt buộc cho câu hỏi về liên hệ chính thức, admin, số điện thoại, "
                "hotline, Zalo, hoặc 'đến công ty liên hệ ai'. Không dùng cho câu hỏi lịch xe có tuyến/"
                "điểm đón/giờ đón; các câu đó phải dùng search_bus_timetable trước."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_slug": {
                        "type": "string",
                        "description": "slug dự án (từ danh mục) để giới hạn tìm kiếm",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_projects",
            "description": (
                "Gợi ý các dự án/sản phẩm đang hoạt động phù hợp với nhu cầu ứng viên. "
                "Dùng trước tiên khi ứng viên hỏi 'có việc nào phù hợp', 'gợi ý việc', "
                "hoặc mô tả nhu cầu tìm việc nhưng chưa chọn dự án cụ thể."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {
                        "type": "integer",
                        "description": "Số dự án cần gợi ý, tối đa 5",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_jobs",
            "description": (
                "Gợi ý việc làm ACTIVE phù hợp dựa trên hồ sơ ứng viên (lương mong muốn, "
                "khu vực, vị trí mong muốn, kinh nghiệm). Dùng khi ứng viên đã cung cấp "
                "đủ thông tin hồ sơ và hỏi 'có việc nào phù hợp'. Mỗi gợi ý kèm lý do cụ thể. "
                "Ưu tiên dùng công cụ này trước recommend_projects khi đã có hồ sơ."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "chat_id (zalo_id) của ứng viên để tải hồ sơ",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Số việc cần gợi ý, mặc định 3, tối đa 10",
                    },
                    "province": {
                        "type": "string",
                        "description": "Lọc theo tỉnh/thành (tùy chọn); để trống để tìm toàn quốc",
                    },
                },
                "required": ["chat_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_bus_timetable",
            "description": (
                "Tra cứu lịch xe đưa đón công nhân theo công ty. Dùng trước tiên cho mọi câu hỏi về tuyến xe, "
                "điểm đón, giờ đón, ca ngày/ca đêm, hoặc địa điểm như Hào Quang/Kiến An/An Lão. Tool trả "
                "về tuyến đầy đủ kèm giờ từng điểm dừng."
            ),
            "parameters": {
                "type": "object",
                "properties": {"company": {"type": "string"}, "question": {"type": "string"}},
                "required": ["company", "question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_features",
            "description": (
                "Lấy các đặc điểm sản phẩm (lương, ca làm, tăng ca, KTX, xe đưa đón, thưởng...) "
                "của một dự án/sản phẩm để tư vấn chính xác. Dùng khi ứng viên hỏi về thu nhập, "
                "lịch ca, phụ cấp, nhà ở, hồ sơ... của một dự án cụ thể. Không dùng để tra tuyến/điểm/giờ "
                "xe; khi hỏi lịch xe chi tiết phải dùng search_bus_timetable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_slug": {
                        "type": "string",
                        "description": "slug dự án/sản phẩm (từ danh mục) cần lấy đặc điểm",
                    }
                },
                "required": ["project_slug"],
            },
        },
    },
]


# Tools the agent may always reach for, regardless of routing — a safety floor so
# the model can still self-correct (e.g. a "recommend" turn that turns out to be a
# contact question can still call search_knowledge without being artificially gated).
_ALWAYS_AVAILABLE = frozenset({"search_knowledge", "search_user_memory"})

# Confidence below which the router is treated as uncertain and the FULL toolset is
# bound (current behavior). Keeps low-confidence turns unconstrained.
ROUTE_CONFIDENCE_FLOOR = 0.5


def filter_tool_schemas(
    allowed: tuple[str, ...] | None,
    *,
    resolved_registry: frozenset[str] | None = None,
) -> list[dict]:
    """Return the tool-schema subset the agent is permitted to bind this turn.

    ``allowed`` is the routed tool set (``TurnRoute.tools``). The safety-floor tools
    (``search_knowledge``, ``search_user_memory``) are always included so the agent can
    still recover from a mis-route. ``None`` or empty → full registry (current behavior,
    used for low-confidence / un-routed turns).
    """
    if resolved_registry is not None:
        wanted = set(resolved_registry)
        if allowed:
            wanted.intersection_update(allowed)
        return [schema for schema in TOOL_SCHEMAS if schema["function"]["name"] in wanted]
    if not allowed:
        return TOOL_SCHEMAS
    wanted = set(allowed) | set(_ALWAYS_AVAILABLE)
    return [s for s in TOOL_SCHEMAS if s["function"]["name"] in wanted]


async def _dispatch_tool(
    retrieval,
    embedder,
    name: str,
    args: dict,
    *,
    metrics: dict | None = None,
    resolved_registry: frozenset[str] | None = None,
) -> str:
    """Route a named tool call to its function.

    Errors are caught and returned as strings so the LLM sees the failure in the
    ToolMessage and can self-correct (retry, try a different tool, or answer from
    context) instead of crashing the entire agent loop.

    ``metrics`` is forwarded to tools that record cache/lookup telemetry
    (currently only ``search_knowledge``); other tools ignore it.
    """
    import time

    name = (name or "").strip()
    args = args or {}
    if resolved_registry is not None and name not in resolved_registry:
        logger.warning("disabled tool dispatch blocked: %s", name)
        return "tool is disabled for the active installation"
    try:
        t0 = time.monotonic()
        if name == "search_user_memory":
            result = await search_user_memory(
                retrieval, embedder, args.get("chat_id", ""), args.get("query", "")
            )
        elif name == "search_knowledge":
            result = await search_knowledge(
                retrieval,
                embedder,
                args.get("query", ""),
                args.get("project_slug"),
                metrics=metrics,
            )
        elif name == "list_active_projects":
            result = await list_active_projects(retrieval)
        elif name == "list_active_jobs":
            result = await list_active_jobs(
                retrieval,
                project_slug=args.get("project_slug"),
                role=args.get("role"),
                company=args.get("company"),
                location=args.get("location"),
                top_k=args.get("top_k", 3),
                sort_by=args.get("sort_by"),
            )
        elif name == "recommend_projects":
            result = await recommend_projects(
                retrieval, args.get("query", ""), args.get("top_k", 3)
            )
        elif name == "recommend_jobs":
            result = await recommend_jobs(
                retrieval,
                args.get("chat_id", ""),
                top_k=args.get("top_k", 3),
                province=args.get("province"),
            )
        elif name == "search_bus_timetable":
            result = await search_bus_timetable(
                retrieval,
                args.get("company", ""),
                args.get("question", ""),
                strict_company=bool(args.get("_strict_project_scope")),
            )
        elif name == "get_product_features":
            result = await get_product_features(retrieval, args.get("project_slug", ""))
        else:
            logger.warning("unknown tool dispatched: %s", name)
            return "unknown tool"
        logger.debug(
            "tool %s completed in %.1fms (%d chars)",
            name,
            (time.monotonic() - t0) * 1000,
            len(result),
        )
        return result
    except Exception as exc:
        logger.warning("tool %s failed error_type=%s", name, type(exc).__name__)
        return f"Lỗi khi gọi tool '{name}': vui lòng thử lại hoặc dùng cách khác."
