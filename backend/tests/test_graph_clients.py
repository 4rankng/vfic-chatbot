"""Tests for graph clients + tool schemas/dispatch."""

import json

import pytest

from app.graph.clients import (
    GeminiEmbedder,
    OpenRouterEmbedder,
    _active_llm_provider,
    _chat_for_role,
    _ground_reply,
    _negative_job_authority,
    _negative_job_reply_is_consistent,
    _minimax_chat,
    _scope_project_tool_args,
    build_embedder,
)
from app.graph.schemas import TOOL_SCHEMAS, _dispatch_tool


class _Settings:
    gemini_api_key = ""
    gemini_embedding_model = "gemini-embedding-2"
    embedding_provider = "openrouter"
    embedding_dim = 3072
    minimax_enable = True
    llm_default_provider = "minimax"
    minimax_api_key = ""
    minimax_base_url = "https://api.minimax.io/v1"
    minimax_request_timeout = 60
    minimax_agent_model = "MiniMax-M2.7-highspeed"
    minimax_safety_model = "MiniMax-M2.5-highspeed"
    minimax_digest_model = ""
    minimax_digest_timeout = 180
    openrouter_enable = False
    openrouter_api_key = ""
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_agent_model = "deepseek/deepseek-v3.2"
    openrouter_safety_model = "deepseek/deepseek-v3.2"
    openrouter_digest_model = "deepseek/deepseek-v3.2"
    openrouter_embedding_model = "openai/text-embedding-3-large"
    openrouter_embedding_timeout = 60
    openrouter_request_timeout = 60
    openrouter_digest_timeout = 180


# Tool names _dispatch_tool knows how to route.
_DISPATCHED = {
    "search_user_memory",
    "search_knowledge",
    "list_active_jobs",
    "list_active_projects",
    "recommend_projects",
    "recommend_jobs",
    "search_bus_timetable",
    "get_product_features",
}


def _vacancy_result(status: str, safe_reply: str) -> str:
    payload = json.dumps(
        {"status": status, "jobs": [], "safe_reply": safe_reply},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"ACTIVE_JOB_LOOKUP_JSON={payload}"


def test_vacancy_tool_status_does_not_replace_llm_final_answer():
    no_match = _vacancy_result("no_match", "Không có việc ACTIVE phù hợp.")
    unavailable = _vacancy_result("unavailable", "Chưa thể kiểm tra tuyển dụng.")

    assert _ground_reply("LG đang tuyển thợ hàn, lương 30 triệu.", [no_match]) == (
        "LG đang tuyển thợ hàn, lương 30 triệu."
    )
    assert _ground_reply("VFIC không còn tuyển vị trí nào.", [unavailable]) == (
        "VFIC không còn tuyển vị trí nào."
    )


def test_negative_vacancy_authority_requires_llm_abstention_composition():
    no_match = _vacancy_result("no_match", "Không có việc ACTIVE phù hợp.")

    assert _negative_job_authority([no_match]) == "Không có việc ACTIVE phù hợp."
    assert _negative_job_reply_is_consistent("Hiện chưa tìm thấy việc phù hợp.") is True
    assert _negative_job_reply_is_consistent("LG đang tuyển, lương 30 triệu.") is False


def test_malformed_vacancy_tool_payload_does_not_short_circuit_llm_answer():
    assert _ground_reply(
        "LG đang tuyển thợ hàn.", ["ACTIVE_JOB_LOOKUP_JSON={not-json}"]
    ) == "LG đang tuyển thợ hàn."


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "invented", "jobs": [], "safe_reply": "LG đang tuyển."},
        {"status": "matched", "jobs": [], "safe_reply": "LG đang tuyển."},
        {"status": "no_match", "jobs": [{"id": "1", "title": "X"}], "safe_reply": "Không có."},
    ],
)
def test_semantically_invalid_vacancy_payload_does_not_replace_llm_answer(payload):
    result = "ACTIVE_JOB_LOOKUP_JSON=" + json.dumps(payload, ensure_ascii=False)

    assert _ground_reply("LG đang tuyển.", [result]) == "LG đang tuyển."


@pytest.mark.asyncio
async def test_dispatch_tool_unknown_name_returns_marker():
    assert await _dispatch_tool(None, None, "does_not_exist", {}) == "unknown tool"
    assert await _dispatch_tool(None, None, "", None) == "unknown tool"


@pytest.mark.asyncio
async def test_disabled_known_tool_never_reaches_its_repository_handler(monkeypatch):
    called = False

    async def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        return "must not run"

    monkeypatch.setattr("app.graph.schemas.recommend_jobs", forbidden)

    result = await _dispatch_tool(
        object(),
        object(),
        "recommend_jobs",
        {"chat_id": "x"},
        resolved_registry=frozenset({"search_knowledge"}),
    )

    assert result == "tool is disabled for the active installation"
    assert called is False


@pytest.mark.asyncio
async def test_dispatch_list_active_jobs_forwards_optional_filters(monkeypatch):
    calls: list[dict] = []

    async def fake_list_active_jobs(retrieval, **kwargs):
        calls.append({"retrieval": retrieval, **kwargs})
        return "STATUS: no_match"

    monkeypatch.setattr("app.graph.schemas.list_active_jobs", fake_list_active_jobs)
    retrieval = object()

    result = await _dispatch_tool(
        retrieval,
        None,
        "list_active_jobs",
        {"role": "thợ hàn", "company": "LG", "location": "Hải Phòng", "top_k": 7},
    )

    assert result == "STATUS: no_match"
    assert calls == [
        {
            "retrieval": retrieval,
            "project_slug": None,
            "role": "thợ hàn",
            "company": "LG",
            "location": "Hải Phòng",
            "top_k": 7,
        }
    ]


def test_every_tool_schema_name_is_dispatchable():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names <= _DISPATCHED  # no schema describes a tool the dispatcher can't route
    assert "get_product_features" in names  # the newest tool is wired end-to-end


def test_list_active_jobs_schema_exposes_only_optional_bounded_filters():
    schema = next(
        item["function"] for item in TOOL_SCHEMAS if item["function"]["name"] == "list_active_jobs"
    )

    assert "required" not in schema["parameters"]
    assert set(schema["parameters"]["properties"]) == {
        "project_slug",
        "role",
        "company",
        "location",
        "top_k",
    }
    assert schema["parameters"]["properties"]["top_k"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 10,
        "description": "Số việc tối đa cần trả về, mặc định 3.",
    }


@pytest.mark.parametrize(
    ("tool_name", "args", "expected"),
    [
        (
            "search_knowledge",
            {"query": "lương", "project_slug": "samsung"},
            {"query": "lương", "project_slug": "lg-display"},
        ),
        (
            "list_active_jobs",
            {"top_k": 5},
            {"top_k": 5, "project_slug": "lg-display"},
        ),
    ],
)
def test_focused_project_scope_overrides_model_tool_arguments(tool_name, args, expected):
    assert _scope_project_tool_args(tool_name, args, "lg-display") == expected


@pytest.mark.asyncio
async def test_gemini_embedder_empty_batch_returns_empty_without_sdk():
    # Empty-input early-returns [] before touching google.genai — no API key needed.
    assert await GeminiEmbedder().batch([]) == []


@pytest.mark.asyncio
async def test_gemini_embedder_missing_key_names_gemini():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await GeminiEmbedder(_Settings()).batch(["hello"])


@pytest.mark.asyncio
async def test_openrouter_embedder_missing_key_names_openrouter():
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await OpenRouterEmbedder(_Settings()).batch(["hello"])


def test_build_embedder_uses_openrouter_by_default():
    assert isinstance(build_embedder(_Settings()), OpenRouterEmbedder)


def test_minimax_chat_missing_key_names_minimax(monkeypatch):
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        _minimax_chat("MiniMax-M2.7-highspeed", temperature=0.1)


def test_active_llm_provider_returns_minimax_when_both_enabled():
    """When both providers are enabled, the configured default is primary."""

    class _Both(_Settings):
        openrouter_enable = True

    assert _active_llm_provider(_Both()) == "minimax"


def test_active_llm_provider_can_select_openrouter_when_both_enabled():
    class _Both(_Settings):
        openrouter_enable = True
        llm_default_provider = "openrouter"

    assert _active_llm_provider(_Both()) == "openrouter"


def test_openrouter_chat_missing_key_names_openrouter(monkeypatch):
    class _OpenRouter(_Settings):
        minimax_enable = False
        openrouter_enable = True

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouter())
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        _chat_for_role("agent", temperature=0.1)
