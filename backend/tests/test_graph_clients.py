"""Tests for graph clients + tool schemas/dispatch."""

import json

import pytest

from app.graph.clients import (
    GeminiEmbedder,
    OpenRouterEmbedder,
    _active_llm_provider,
    _chat_for_role,
    _minimax_chat,
    _openrouter_chat,
    build_embedder,
)
from app.graph.grounding import (
    ground_active_job_reply as _ground_active_job_reply,
    ground_reply as _ground_reply,
    negative_job_authority as _negative_job_authority,
)
from app.graph.income_contract import IncomeVerdict, build_income_verdict, safe_reply_from
from app.graph.prefetch import _scope_project_tool_args
from app.graph.reasoning_compat import (
    _extract_returned_reasoning,
    _reasoning_chat_class,
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
    "compare_income",
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
    # The reply-consistency regex gate was removed. Actual authority turns now
    # use this trusted renderer output directly, without a third model rewrite.


def test_negative_vacancy_reply_uses_trusted_text_without_llm_rewrite():
    no_match = _vacancy_result("no_match", "Không có việc ACTIVE phù hợp.")

    assert (
        _ground_active_job_reply("LG đang tuyển, lương 30 triệu.", [no_match])
        == "Không có việc ACTIVE phù hợp."
    )
    assert (
        _ground_active_job_reply("Hiện chưa có vị trí phù hợp.", [no_match])
        == "Không có việc ACTIVE phù hợp."
    )


def test_compare_income_safe_reply_rejects_mismatched_or_contradictory_payload():
    payload = {
        "status": "matched",
        "target_monthly_vnd": 15_000_000,
        "projects": [
            {
                "project_name": "Rorze",
                "evidence": [
                    {
                        "name_vi": "Thu nhập",
                        "value_text": "20-21 triệu/tháng bình quân năm gồm thưởng.",
                    }
                ],
            }
        ],
        "safe_reply": "Hiện chưa có dự án nào đạt 20 triệu.",
    }
    tool_result = "COMPARE_INCOME_JSON=" + json.dumps(payload, ensure_ascii=False)

    assert (
        safe_reply_from(
            tool_result,
            expected_target_monthly_vnd=20_000_000,
        )
        is None
    )
    payload["target_monthly_vnd"] = 20_000_000
    tool_result = "COMPARE_INCOME_JSON=" + json.dumps(payload, ensure_ascii=False)
    assert (
        safe_reply_from(
            tool_result,
            expected_target_monthly_vnd=20_000_000,
        )
        is None
    )


def test_safe_reply_from_consumes_typed_verdict_from_contract():
    """The tool's typed IncomeVerdict is consumed field-wise, no JSON re-parse."""
    projects = [
        {
            "project_slug": "rorze",
            "project_name": "Rorze",
            "evidence": [
                {
                    "name_vi": "Thu nhập",
                    "value_text": "20-21 triệu/tháng bình quân năm gồm thưởng.",
                }
            ],
        }
    ]
    verdict = build_income_verdict(projects, target_monthly_vnd=20_000_000)

    assert isinstance(verdict, IncomeVerdict)
    assert verdict.status == "matched"
    assert safe_reply_from(verdict, expected_target_monthly_vnd=20_000_000) == verdict.safe_reply
    assert safe_reply_from(verdict, expected_target_monthly_vnd=15_000_000) is None


def test_matched_vacancy_reply_uses_structured_safe_reply_deterministically():
    payload = json.dumps(
        {
            "status": "matched",
            "jobs": [
                {
                    "id": "11111111-1111-4111-8111-111111111111",
                    "title": "Công nhân sản xuất",
                    "company": "LG Display",
                    "salary_min": 10_000_000,
                    "salary_max": 14_000_000,
                }
            ],
            "safe_reply": "LG Display tuyển công nhân, lương 10-14 triệu.",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    tool_result = f"ACTIVE_JOB_LOOKUP_JSON={payload}"

    assert (
        _ground_active_job_reply("LG Display tuyển, lương 30 triệu.", [tool_result])
        == "LG Display tuyển công nhân, lương 10-14 triệu."
    )
    grounded = "LG Display tuyển công nhân, lương 10-14 triệu."
    assert _ground_active_job_reply(grounded, [tool_result]) == grounded


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


@pytest.mark.asyncio
async def test_dispatch_compare_income_forwards_target(monkeypatch):
    calls: list[dict] = []

    async def fake_compare_income(retrieval, **kwargs):
        calls.append({"retrieval": retrieval, **kwargs})
        return "COMPARE_INCOME_JSON={}"

    monkeypatch.setattr("app.graph.schemas.compare_income", fake_compare_income)
    retrieval = object()

    result = await _dispatch_tool(
        retrieval,
        None,
        "compare_income",
        {"target_monthly_vnd": 20_000_000},
    )

    assert result == "COMPARE_INCOME_JSON={}"
    assert calls == [
        {
            "retrieval": retrieval,
            "target_monthly_vnd": 20_000_000,
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


def test_openrouter_agent_client_disables_reasoning_by_default(monkeypatch):
    """The agent lane no longer pins effort=high; it asks for no reasoning.

    ``effort: high`` was only there to capture chain-of-thought into the decision
    trace, which the candidate never sees, and it multiplied wall time on
    reasoning models. Default is now ``off``.
    """

    class _OpenRouter(_Settings):
        openrouter_api_key = "test-key"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouter())

    chat = _openrouter_chat(
        "deepseek/deepseek-v4-flash",
        temperature=0.1,
        reasoning_mode="off",
    )

    assert chat.trace_provider == "openrouter"
    assert chat.extra_body == {"reasoning": {"enabled": False}}


def test_openrouter_agent_client_supports_low_reasoning(monkeypatch):
    class _OpenRouter(_Settings):
        openrouter_api_key = "test-key"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouter())

    chat = _openrouter_chat(
        "deepseek/deepseek-v4-flash",
        temperature=0.1,
        reasoning_mode="low",
    )

    assert chat.extra_body == {"reasoning": {"effort": "low", "exclude": False}}


def test_openrouter_agent_client_default_mode_sends_no_reasoning_field(monkeypatch):
    """``default`` defers to the provider (used by safety/digest roles)."""

    class _OpenRouter(_Settings):
        openrouter_api_key = "test-key"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouter())

    chat = _openrouter_chat("deepseek/deepseek-v4-flash", temperature=0.0, reasoning_mode="default")

    assert not hasattr(chat, "extra_body") or not chat.extra_body


def test_openrouter_chat_marks_stable_system_block_as_cacheable_prefix(monkeypatch):
    class _OpenRouter(_Settings):
        openrouter_api_key = "test-key"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouter())

    chat = _openrouter_chat("deepseek/deepseek-v4-flash", temperature=0.1)
    langchain_core = pytest.importorskip("langchain_core.messages")
    stable = "Bạn là trợ lý..."  # byte-stable preamble text
    payload = chat._get_request_payload(
        [
            langchain_core.SystemMessage(content=stable),
            langchain_core.HumanMessage(content="Câu hỏi của khách"),
        ]
    )

    first = payload["messages"][0]
    assert first["role"] == "system"
    assert isinstance(first["content"], list)
    assert first["content"] == [
        {
            "type": "text",
            "text": stable,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    # The turn-varying message after the prefix stays unmarked plain text.
    assert payload["messages"][1]["content"] == "Câu hỏi của khách"


def test_minimax_chat_sends_no_cache_marker_on_openai_compatible_endpoint(monkeypatch):
    class _MiniMax(_Settings):
        minimax_api_key = "test-key"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _MiniMax())

    chat = _minimax_chat("MiniMax-M2.7-highspeed", temperature=0.1)
    langchain_core = pytest.importorskip("langchain_core.messages")
    payload = chat._get_request_payload(
        [
            langchain_core.SystemMessage(content="preamble"),
            langchain_core.HumanMessage(content="hi"),
        ]
    )

    # MiniMax's OpenAI-compatible API caches the prefix automatically and
    # documents no marker for it — the request must carry none. Guarding this
    # keeps any future marker an explicit, deliberate change.
    assert chat.system_prefix_cache_control == {}
    assert payload["messages"][0]["content"] == "preamble"


def test_minimax_chat_sends_no_reasoning_field(monkeypatch):
    """MiniMax's OpenAI-compatible endpoint exposes no thinking switch.

    Measured: thinking/enable_thinking/reasoning/reasoning_effort/chat_template_kwargs
    all left 120-220 reasoning tokens in place, so the builder must not send an
    unsupported field that could 4xx the primary lane.
    """

    class _MiniMax(_Settings):
        minimax_api_key = "test-key"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _MiniMax())

    chat = _minimax_chat("MiniMax-M2.7-highspeed", temperature=0.1)
    langchain_core = pytest.importorskip("langchain_core.messages")
    payload = chat._get_request_payload(
        [langchain_core.HumanMessage(content="hi"), langchain_core.HumanMessage(content="again")]
    )

    assert "thinking" not in payload
    assert "reasoning" not in payload
    assert "reasoning_effort" not in payload


def test_minimax_chat_applies_output_cap(monkeypatch):
    class _MiniMax(_Settings):
        minimax_api_key = "test-key"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _MiniMax())

    capped = _minimax_chat("MiniMax-M2.7-highspeed", temperature=0.1, max_tokens=400)
    uncapped = _minimax_chat("MiniMax-M2.7-highspeed", temperature=0.1)

    assert capped.max_tokens == 400
    assert uncapped.max_tokens is None


def test_custom_chat_disables_thinking_on_known_token_plan(monkeypatch):
    """MiMo on the Xiaomi token plan honours ``thinking:{type:disabled}``."""

    class _Custom(_Settings):
        custom_llm_request_timeout = 60

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Custom())

    from app.graph.clients import _custom_chat

    chat = _custom_chat(
        "mimo-v2.6-flash",
        temperature=0.3,
        api_key="test-key",
        base_url="https://token-plan-sgp.xiaomimimo.com/v1",
        reasoning_mode="off",
    )

    assert chat.extra_body == {"thinking": {"type": "disabled"}}


def test_custom_chat_leaves_unknown_vendor_reasoning_untouched(monkeypatch):
    """An operator-supplied vendor must not receive an undocumented field."""

    class _Custom(_Settings):
        custom_llm_request_timeout = 60

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Custom())

    from app.graph.clients import _custom_chat

    chat = _custom_chat(
        "some-model",
        temperature=0.3,
        api_key="test-key",
        base_url="https://api.unknown-vendor.example/v1",
        reasoning_mode="off",
    )

    assert not chat.extra_body


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
    """The trusted abstention text is surfaced from the active-job payload.

    The reply-consistency regex gates that consumed this output (and fired a
    third ``self.direct()`` LLM call) were removed — they over-fired on
    legitimate replies (the no_match safe_reply itself contains "lương" for
    alternatives; salary reformulation like 7000000→"7 triệu" never matches the
    raw JSON digits). Actual authority turns now return the structured safe
    reply directly. This test pins that extraction contract.
    """
    fake_active_job_output = (
        'ACTIVE_JOB_LOOKUP_JSON={"status":"no_match","total":0,"jobs":[],'
        '"safe_reply":"Không có việc ACTIVE."}'
    )
    assert _negative_job_authority([fake_active_job_output]) == "Không có việc ACTIVE."


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
