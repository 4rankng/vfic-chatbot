"""Production LLM/embedder wiring (MiniMax M2.7 agent + M2.5 safety + Gemini embed).

Imported LAZILY only inside the RQ worker (app/workers/chatbot_worker.py), so the app
and the test suite never need langchain-openai / google-genai at import time. Live
behavior (acceptance #4 grounding / #5 off-topic) is exercised through this module;
keys live server-side in .env only.
"""
from __future__ import annotations

import logging

from app.core.config import get_settings
from app.graph.tools import (
    list_active_projects,
    search_bus_timetable,
    search_jobs,
    search_knowledge,
    search_user_memory,
)

logger = logging.getLogger(__name__)


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
    return "unknown tool"


class GeminiEmbedder:
    def __init__(self, settings=None) -> None:
        self.s = settings or get_settings()
        self._client = None

    async def batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in ONE SDK call (Gemini accepts a `contents` list).

        Replaces the N+1 pattern of calling embed() per fact in MemoryService.save.
        """
        from google import genai

        if not texts:
            return []
        if self._client is None:
            self._client = genai.Client(api_key=self.s.gemini_api_key)
        resp = await self._client.aio.models.embed_content(
            model=self.s.gemini_embedding_model, contents=texts
        )
        return [list(e.values) for e in resp.embeddings]

    async def embed(self, text: str) -> list[float]:
        return (await self.batch([text]))[0]

    # The graph wires this object where the Embedder Callable[[str], ...] contract is
    # expected (tools.py does `await embedder(query)`), so the instance must be callable.
    __call__ = embed


class MiniMaxAgent:
    """Tool-calling agent: loops on MiniMax tool_calls until a final text reply."""

    def __init__(self, llm, embedder, max_iters: int = 4) -> None:
        self.llm = llm
        self.embedder = embedder
        self.max_iters = max_iters

    async def agent(self, user_text, *, system, db, embedder) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        bound = self.llm.bind_tools(TOOL_SCHEMAS) if hasattr(self.llm, "bind_tools") else self.llm
        messages = [SystemMessage(content=system), HumanMessage(content=user_text)]
        for _ in range(self.max_iters):
            ai = await bound.ainvoke(messages)
            messages.append(ai)
            calls = getattr(ai, "tool_calls", None)
            if not calls:
                return ai.content
            # MiniMax occasionally omits tool_call.id; an empty tool_call_id breaks
            # the OpenAI tool protocol on the next turn. Synthesize a stable id.
            for idx, tc in enumerate(calls):
                out = await _dispatch_tool(db, embedder, tc["name"], tc.get("args", {}))
                messages.append(
                    ToolMessage(
                        content=str(out),
                        tool_call_id=tc.get("id") or f"call_{idx}_{tc.get('name', 'tool')}",
                    )
                )
        return messages[-1].content if hasattr(messages[-1], "content") else ""


class MiniMaxSafety:
    def __init__(self, llm) -> None:
        self.llm = llm

    async def safety(self, candidate_reply: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.graph.prompts import SAFETY_PROMPT

        resp = await self.llm.ainvoke(
            [SystemMessage(content=SAFETY_PROMPT), HumanMessage(content=candidate_reply)]
        )
        return resp.content


def _minimax_chat(model: str, *, temperature: float):
    """OpenAI-compatible MiniMax client from settings. Shared construction so
    model / base_url / timeout cannot drift between build_deps and the extractor.
    """
    from langchain_openai import ChatOpenAI

    s = get_settings()
    return ChatOpenAI(
        model=model,
        api_key=s.minimax_api_key,
        base_url=s.minimax_base_url,
        timeout=s.minimax_request_timeout,
        temperature=temperature,
    )


def build_minimax_extractor():
    """MiniMax extractor (safety model, temp 0) for lead/memory extraction.

    Shared by the persistence worker's lead + memory jobs so they cannot drift
    from the safety-LLM wiring in build_deps.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _minimax_chat(get_settings().minimax_safety_model, temperature=0.0)

    async def extractor(system: str, user: str) -> str:
        return (await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])).content

    return extractor


def make_minimax_llm_json():
    """(system, user) -> json_text callable for the LLM training pipeline.

    OpenAI-compatible MiniMax client with JSON-object response mode. Falls back to the
    agent model when MINIMAX_DIGEST_MODEL is unset. Imported lazily by the ingest worker
    only, so the app/tests never need langchain-openai at import time.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    s = get_settings()
    llm = ChatOpenAI(
        model=s.minimax_digest_model or s.minimax_agent_model,
        api_key=s.minimax_api_key,
        base_url=s.minimax_base_url,
        timeout=s.minimax_request_timeout,
        temperature=0.1,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    async def _call(system: str, user: str) -> str:
        return (await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])).content

    return _call


async def build_deps(db):
    from app.graph.runner import GraphDeps
    from app.services.zalo_service import ZaloMessageService

    s = get_settings()
    agent_llm = _minimax_chat(s.minimax_agent_model, temperature=0.3)
    safety_llm = _minimax_chat(s.minimax_safety_model, temperature=0.0)
    embedder = GeminiEmbedder(s)
    return GraphDeps(
        db=db,
        agent=MiniMaxAgent(agent_llm, embedder),
        safety=MiniMaxSafety(safety_llm),
        embedder=embedder,
        zalo=ZaloMessageService(),
    )
