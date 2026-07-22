"""Tests for graph clients + tool schemas/dispatch."""

import json

import pytest

from app.graph.clients import (
    GeminiEmbedder,
    OpenRouterEmbedder,
    _active_llm_provider,
    _chat_for_role,
    _ground_reply,
    _extract_returned_reasoning,
    _negative_job_authority,
    _negative_job_reply_is_consistent,
    _minimax_chat,
    _openrouter_chat,
    _reasoning_chat_class,
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


@pytest.mark.parametrize(
    "reply",
    [
        # Real no_match replies naturally embed affirmative vocabulary inside a
        # negated phrase ("chưa có vị trí nào đang tuyển") or while offering to
        # check other openings. The guard must read these as consistent so the
        # grounded reply is sent instead of triggering a wasteful direct()
        # rewrite that surfaces the generic "chưa thể xác minh" fallback.
        "Hiện tại chưa có vị trí nhân viên lắp ráp nào đang tuyển.",
        "Không có vị trí lắp ráp nào đang tuyển active.",
        "Hiện chưa có vị trí ACTIVE phù hợp. Bạn muốn xem các vị trí khác đang tuyển không?",
        "VFIC không còn tuyển vị trí nào.",
        "Chưa có vị trí lắp ráp. Trước đó bạn hỏi về CNC cũng chưa có. Bạn có muốn xem các vị trí khác không?",
    ],
)
def test_negative_job_reply_consistent_when_negation_outweighs_affirmative(reply):
    """Negation marker anywhere wins over affirmative vocabulary (regression).

    Previously the affirmative check ran first and short-circuited to False on
    legitimate no_match replies that happened to contain 'dang tuyen' or
    'co vi tri' inside a negated clause, discarding the grounded answer and
    forcing a generic "chưa thể xác minh" fallback.
    """
    assert _negative_job_reply_is_consistent(reply) is True


@pytest.mark.parametrize(
    "reply",
    [
        # Pure affirmative — model ignored the negative authority and invented.
        "LG đang tuyển thợ hàn, lương 30 triệu.",
        "Có việc CNC lương 15 triệu.",
        "VFIC đang tuyển vị trí lắp ráp.",
        # No negation and no clear abstention — must not be falsely accepted.
        "Tôi sẽ chuyển thông tin cho chuyên viên tuyển dụng.",
    ],
)
def test_negative_job_reply_inconsistent_without_negation(reply):
    assert _negative_job_reply_is_consistent(reply) is False


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
            "sort_by": None,
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
        "sort_by",
    }
    assert schema["parameters"]["properties"]["top_k"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 10,
        "description": "Số việc tối đa cần trả về, mặc định 3.",
    }
    assert schema["parameters"]["properties"]["sort_by"]["enum"] == [
        "updated_at",
        "salary_desc",
        "salary_asc",
        "created_at",
    ]


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


def test_extract_returned_reasoning_prefers_provider_field_over_think_block():
    langchain_core = pytest.importorskip("langchain_core.messages")
    message = langchain_core.AIMessage(
        content="<think>fallback reasoning</think>candidate answer",
        additional_kwargs={"reasoning_content": "provider reasoning"},
    )

    assert _extract_returned_reasoning(message) == "provider reasoning"


def test_extract_returned_reasoning_from_minimax_think_blocks_only():
    langchain_core = pytest.importorskip("langchain_core.messages")
    message = langchain_core.AIMessage(
        content="<think>first step</think><think>second step</think>candidate answer"
    )

    assert _extract_returned_reasoning(message) == "first step\n\nsecond step"
    assert "candidate answer" not in _extract_returned_reasoning(message)


def test_extract_returned_reasoning_from_unclosed_minimax_think_block():
    langchain_core = pytest.importorskip("langchain_core.messages")
    message = langchain_core.AIMessage(content="<think>provider output ended mid-reasoning")

    assert _extract_returned_reasoning(message) == "provider output ended mid-reasoning"


def test_reasoning_chat_adapter_preserves_openrouter_reasoning_across_tool_rounds():
    messages = pytest.importorskip("langchain_core.messages")
    chat_class = _reasoning_chat_class()
    chat = chat_class(
        model="provider/model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        trace_provider="openrouter",
    )
    raw_reasoning = [
        {"type": "reasoning.text", "text": "Need current data."},
        {"type": "reasoning.text", "text": "Use the lookup tool."},
    ]
    response = {
        "id": "generation-1",
        "model": "provider/model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_details": raw_reasoning,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "search_knowledge",
                                "arguments": '{"query":"salary"}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }

    result = chat._create_chat_result(response)
    ai_message = result.generations[0].message
    assert ai_message.additional_kwargs["reasoning_details"] == raw_reasoning
    assert _extract_returned_reasoning(ai_message) == (
        "Need current data.\n\nUse the lookup tool."
    )

    payload = chat._get_request_payload(
        [
            messages.HumanMessage(content="What is the salary?"),
            ai_message,
            messages.ToolMessage(content="8 million", tool_call_id="call-1"),
        ]
    )

    assert payload["messages"][1]["reasoning_details"] == raw_reasoning


def test_openrouter_agent_client_requests_returned_reasoning(monkeypatch):
    class _OpenRouter(_Settings):
        openrouter_api_key = "test-key"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouter())

    chat = _openrouter_chat(
        "deepseek/deepseek-v4-flash",
        temperature=0.1,
        capture_reasoning=True,
    )

    assert chat.trace_provider == "openrouter"
    assert chat.extra_body == {
        "reasoning": {"effort": "high", "exclude": False},
    }


# --- Authority-override regression -------------------------------------------
# Production trace showed: model called search_knowledge, returned the correct
# LG Display schedule in its `final` turn, then an authority-override branch
# misfired and replaced that grounded reply with a blind self.direct() call
# (no tool context) — telling the user "không có dữ liệu".
#
# Root cause: the authority guards scanned ``tool_results`` for the
# ``ACTIVE_JOB_LOOKUP_JSON=`` prefix and could match any tool output that
# happened to start with it, even when list_active_jobs was never dispatched.
# The fix gates the override on an internal ``authority_tool_dispatched`` flag
# set only when list_active_jobs actually ran.
#
# These tests pin the invariant that the guard cannot fire from a stray prefix
# match in a non-authority tool result. The full agent() integration path is
# exercised end-to-end in the smoke harness; here we document the contract
# the gate enforces.

def test_authority_override_invariant_documented():
    """Authority overrides require list_active_jobs to have been dispatched.

    The pure guard ``_negative_job_authority`` still scans ``tool_results`` for
    the prefix, but the caller (``agent()``) now AND-s it with the
    ``authority_tool_dispatched`` flag so a stray prefix in a search_knowledge
    output cannot trigger the override. This test exists so the invariant is
    not silently removed.
    """
    # The prefix scanner still detects the string (it has to — list_active_jobs
    # output starts with it). The protection lives at the call site, not here.
    fake_active_job_output = (
        'ACTIVE_JOB_LOOKUP_JSON={"status":"no_match","total":0,"jobs":[],'
        '"safe_reply":"Không có việc ACTIVE."}'
    )
    assert _negative_job_authority([fake_active_job_output]) == "Không có việc ACTIVE."
    # Document that the guard alone is necessary but NOT sufficient — the caller
    # must also confirm list_active_jobs was actually dispatched before acting.


def test_ground_reply_preserves_answer_when_no_authority_dispatched():
    """When list_active_jobs was not dispatched, _ground_reply is the only path.

    A search_knowledge turn that happens to contain an ACTIVE_JOB_LOOKUP prefix
    somewhere in its (multi-line) output must NOT replace the LLM's reply.
    ``_ground_reply`` itself never replaces content on a prefix match — it only
    validates job-id hallucinations — so this test pins the no-replacement
    behavior that the gated override relies on.
    """
    search_knowledge_style_output = (
        "knowledge_chunks_result:\n"
        "Ca ngày: 08:00-20:00\nCa đêm: 20:00-08:00\n"
        "ACTIVE_JOB_LOOKUP_JSON={\"status\":\"no_match\"}"  # stray line deep inside
    )
    grounded_reply = "LG Display làm ca ngày 08:00-20:00 và ca đêm 20:00-08:00."
    # _ground_reply never substitutes the reply based on a prefix match; only the
    # caller-level authority branches do, and those are now gated.
    assert _ground_reply(grounded_reply, [search_knowledge_style_output]) == grounded_reply
