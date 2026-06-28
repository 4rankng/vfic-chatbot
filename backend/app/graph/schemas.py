"""OpenAI-compatible tool schemas + the tool-call dispatcher.

Co-located with the agent tools (``app.graph.tools``) the schemas describe. ``_dispatch_tool``
routes a named tool call to its function; used by ``MiniMaxAgent``'s tool loop in
``clients.py``.
"""
from __future__ import annotations

from app.graph.tools import (
    get_product_features,
    list_active_projects,
    search_bus_timetable,
    search_jobs,
    search_knowledge,
    search_user_memory,
)

# OpenAI-compatible function schemas handed to MiniMax (descriptions match n8n).
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
            "description": "Tìm thông tin kiến thức/tuyển dụng trong cơ sở dữ liệu. Truyền project_slug để giới hạn theo một dự án.",
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
            "description": "Tra cứu lịch xe đưa đón công nhân theo công ty.",
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
                "lịch ca, phụ cấp, nhà ở, hồ sơ... của một dự án cụ thể."
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


async def _dispatch_tool(db, embedder, name: str, args: dict) -> str:
    name = (name or "").strip()
    args = args or {}
    if name == "search_user_memory":
        return await search_user_memory(db, embedder, args.get("chat_id", ""), args.get("query", ""))
    if name == "search_knowledge":
        return await search_knowledge(db, embedder, args.get("query", ""), args.get("project_slug"))
    if name == "search_jobs":  # back-compat: older turns may still call this name
        return await search_jobs(db, embedder, args.get("query", ""))
    if name == "list_active_projects":
        return await list_active_projects(db)
    if name == "search_bus_timetable":
        return await search_bus_timetable(db, args.get("company", ""), args.get("question", ""))
    if name == "get_product_features":
        return await get_product_features(db, args.get("project_slug", ""))
    return "unknown tool"
