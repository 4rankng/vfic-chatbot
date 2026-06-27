"""Phase 4 characterization tests for graph clients + tool schemas/dispatch.

Pure (no API keys, no network) — locks the behavior moved out of llm_real.py into
clients.py + schemas.py so the split cannot regress it.
"""
import pytest

from app.graph.clients import GeminiEmbedder
from app.graph.schemas import TOOL_SCHEMAS, _dispatch_tool

# Tool names _dispatch_tool knows how to route (search_jobs is a back-compat alias with
# no schema entry).
_DISPATCHED = {
    "search_user_memory",
    "search_knowledge",
    "search_jobs",
    "list_active_projects",
    "search_bus_timetable",
    "get_product_features",
}


@pytest.mark.asyncio
async def test_dispatch_tool_unknown_name_returns_marker():
    assert await _dispatch_tool(None, None, "does_not_exist", {}) == "unknown tool"
    assert await _dispatch_tool(None, None, "", None) == "unknown tool"


def test_every_tool_schema_name_is_dispatchable():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names <= _DISPATCHED  # no schema describes a tool the dispatcher can't route
    assert "get_product_features" in names  # the newest tool is wired end-to-end


@pytest.mark.asyncio
async def test_gemini_embedder_empty_batch_returns_empty_without_sdk():
    # Empty-input early-returns [] before touching google.genai — no API key needed.
    assert await GeminiEmbedder().batch([]) == []
