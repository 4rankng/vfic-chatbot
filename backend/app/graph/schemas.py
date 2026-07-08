"""OpenAI-compatible tool schemas + the tool-call dispatcher.

Co-located with the agent tools (``app.graph.tools``) the schemas describe. ``_dispatch_tool``
routes a named tool call to its function; used by ``MiniMaxAgent``'s tool loop in
``clients.py``.
"""
from __future__ import annotations

import logging

from app.graph.tools import (
    get_product_features,
    list_active_projects,
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
                    "project_slug": {"type": "string", "description": "slug dự án (từ danh mục) để giới hạn tìm kiếm"},
                },
                "required": ["query"],
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


async def _dispatch_tool(retrieval, embedder, name: str, args: dict) -> str:
    """Route a named tool call to its function.

    Errors are caught and returned as strings so the LLM sees the failure in the
    ToolMessage and can self-correct (retry, try a different tool, or answer from
    context) instead of crashing the entire agent loop.
    """
    import time

    name = (name or "").strip()
    args = args or {}
    try:
        t0 = time.monotonic()
        if name == "search_user_memory":
            result = await search_user_memory(retrieval, embedder, args.get("chat_id", ""), args.get("query", ""))
        elif name == "search_knowledge":
            result = await search_knowledge(retrieval, embedder, args.get("query", ""), args.get("project_slug"))
        elif name == "list_active_projects":
            result = await list_active_projects(retrieval)
        elif name == "search_bus_timetable":
            result = await search_bus_timetable(retrieval, args.get("company", ""), args.get("question", ""))
        elif name == "get_product_features":
            result = await get_product_features(retrieval, args.get("project_slug", ""))
        else:
            logger.warning("unknown tool dispatched: %s (args=%s)", name, args)
            return "unknown tool"
        logger.debug("tool %s completed in %.1fms (%d chars)", name, (time.monotonic() - t0) * 1000, len(result))
        return result
    except Exception:
        logger.warning("tool %s failed (args=%s)", name, args, exc_info=True)
        return f"Lỗi khi gọi tool '{name}': vui lòng thử lại hoặc dùng cách khác."
