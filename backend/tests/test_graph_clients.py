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
from app.graph.grounding import ground_reply as _ground_reply
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
    minimax_extractor_model = "MiniMax-M2.5-highspeed"
    minimax_digest_model = ""
    minimax_digest_timeout = 180
    openrouter_enable = False
    openrouter_api_key = ""
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_agent_model = "deepseek/deepseek-v3.2"
    openrouter_extractor_model = "deepseek/deepseek-v3.2"
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
    "list_active_projects",
    "search_bus_timetable",
    "get_product_features",
    "verify_tingting_identity",
    "send_tingting_otp",
    "confirm_tingting_otp",
    "reset_tingting_password",
}


def _project_lookup_result(status: str, safe_reply: str) -> str:
    payload = json.dumps(
        {"status": status, "total": 0, "projects": [], "safe_reply": safe_reply},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"ACTIVE_PROJECT_LOOKUP_JSON={payload}"


def test_project_lookup_status_does_not_replace_llm_final_answer():
    matched_empty = _project_lookup_result("matched", "Không có dự án nào khớp tiêu chí.")
    unavailable = _project_lookup_result("unavailable", "Chưa thể kiểm tra danh mục dự án.")

    assert _ground_reply("LG đang tuyển thợ hàn, lương 30 triệu.", [matched_empty]) == (
        "LG đang tuyển thợ hàn, lương 30 triệu."
    )
    assert _ground_reply("VFIC không còn tuyển vị trí nào.", [unavailable]) == (
        "VFIC không còn tuyển vị trí nào."
    )


def test_empty_project_match_keeps_llm_answer_intact():
    """A criteria miss stays sanitize-only: the LLM answer is never replaced.

    The operator rule is that the LLM agent owns the final wording; the old
    trusted-text replacements (negative/matched job authority) are gone and
    the active-project payload now carries a presentation contract instead of a
    ready-made reply.
    """
    no_match = _project_lookup_result("matched", "Không có dự án nào khớp tiêu chí.")

    assert _ground_reply("LG đang tuyển thợ hàn, lương 30 triệu.", [no_match]) == (
        "LG đang tuyển thợ hàn, lương 30 triệu."
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


def test_malformed_project_tool_payload_does_not_short_circuit_llm_answer():
    assert _ground_reply(
        "LG đang tuyển thợ hàn.", ["ACTIVE_PROJECT_LOOKUP_JSON={not-json}"]
    ) == "LG đang tuyển thợ hàn."


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "invented", "total": 0, "projects": [], "safe_reply": "LG đang tuyển."},
        {"status": "matched", "total": 1, "projects": [{"id": 5}], "safe_reply": "LG đang tuyển."},
        {
            "status": "catalog_empty",
            "total": 1,
            "projects": [{"id": "11111111-1111-4111-8111-111111111111"}],
            "safe_reply": "Không có.",
        },
    ],
)
def test_semantically_invalid_project_payload_does_not_replace_llm_answer(payload):
    result = "ACTIVE_PROJECT_LOOKUP_JSON=" + json.dumps(payload, ensure_ascii=False)

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

    monkeypatch.setattr("app.graph.schemas.search_bus_timetable", forbidden)

    result = await _dispatch_tool(
        object(),
        object(),
        "search_bus_timetable",
        {"company": "VFIC", "question": "lịch xe"},
        resolved_registry=frozenset({"search_knowledge"}),
    )

    assert result == "tool is disabled for the active installation"
    assert called is False


@pytest.mark.asyncio
async def test_dispatch_list_active_projects_forwards_optional_filters(monkeypatch):
    calls: list[dict] = []

    async def fake_list_active_projects(retrieval, **kwargs):
        calls.append({"retrieval": retrieval, **kwargs})
        return "ACTIVE_PROJECT_LOOKUP_JSON={}"

    monkeypatch.setattr("app.graph.schemas.list_active_projects", fake_list_active_projects)
    retrieval = object()

    result = await _dispatch_tool(
        retrieval,
        None,
        "list_active_projects",
        {
            "project_slug": "rorze",
            "company": "Rorze",
            "job_scope": "lắp ráp",
            "location": "Hải Phòng",
            "salary_min_vnd": 10_000_000,
            "sort_by": "salary_desc",
        },
    )

    assert result == "ACTIVE_PROJECT_LOOKUP_JSON={}"
    assert calls == [
        {
            "retrieval": retrieval,
            "project_slug": "rorze",
            "company": "Rorze",
            "job_scope": "lắp ráp",
            "location": "Hải Phòng",
            "salary_min_vnd": 10_000_000,
            "sort_by": "salary_desc",
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


def test_list_active_projects_schema_exposes_only_optional_filters():
    schema = next(
        item["function"] for item in TOOL_SCHEMAS if item["function"]["name"] == "list_active_projects"
    )

    assert "required" not in schema["parameters"]
    assert set(schema["parameters"]["properties"]) == {
        "project_slug",
        "company",
        "job_scope",
        "location",
        "salary_min_vnd",
        "sort_by",
    }
    assert schema["parameters"]["properties"]["salary_min_vnd"] == {
        "type": "integer",
        "description": "Mức lương tối thiểu ứng viên mong muốn (VND/tháng).",
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
            "list_active_projects",
            {"job_scope": "lắp ráp"},
            {"job_scope": "lắp ráp", "project_slug": "lg-display"},
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
async def test_openrouter_embedder_missing_key_points_at_the_settings_page():
    # The credential is the admin settings page's, so the error says where to
    # set it. It used to name OPENROUTER_API_KEY, which sent operators to a .env
    # they no longer edit; the env var is not a supported source any more.
    with pytest.raises(RuntimeError, match="Settings page"):
        await OpenRouterEmbedder(_Settings()).batch(["hello"])


def test_build_embedder_uses_openrouter_by_default():
    assert isinstance(build_embedder(_Settings()), OpenRouterEmbedder)


def test_minimax_chat_missing_key_names_minimax(monkeypatch):
    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _Settings())
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

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _OpenRouter())
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

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _OpenRouter())

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

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _OpenRouter())

    chat = _openrouter_chat(
        "deepseek/deepseek-v4-flash",
        temperature=0.1,
        reasoning_mode="low",
    )

    assert chat.extra_body == {"reasoning": {"effort": "low", "exclude": False}}


def test_openrouter_agent_client_default_mode_sends_no_reasoning_field(monkeypatch):
    """``default`` defers to the provider (used by extractor/digest roles)."""

    class _OpenRouter(_Settings):
        openrouter_api_key = "test-key"

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _OpenRouter())

    chat = _openrouter_chat("deepseek/deepseek-v4-flash", temperature=0.0, reasoning_mode="default")

    assert not hasattr(chat, "extra_body") or not chat.extra_body


def test_openrouter_chat_marks_stable_system_block_as_cacheable_prefix(monkeypatch):
    class _OpenRouter(_Settings):
        openrouter_api_key = "test-key"

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _OpenRouter())

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

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _MiniMax())

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

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _MiniMax())

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

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _MiniMax())

    capped = _minimax_chat("MiniMax-M2.7-highspeed", temperature=0.1, max_tokens=400)
    uncapped = _minimax_chat("MiniMax-M2.7-highspeed", temperature=0.1)

    assert capped.max_tokens == 400
    assert uncapped.max_tokens is None


def test_custom_chat_disables_thinking_on_known_token_plan(monkeypatch):
    """MiMo on the Xiaomi token plan honours ``thinking:{type:disabled}``."""

    class _Custom(_Settings):
        custom_llm_request_timeout = 60

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _Custom())

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

    monkeypatch.setattr("app.graph.providers.get_settings", lambda: _Custom())

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
# ``ACTIVE_PROJECT_LOOKUP_JSON=`` prefix and could match any tool output that
# happened to start with it, even when list_active_projects was never dispatched.
# The fix gates the override on an internal ``authority_tool_dispatched`` flag
# set only when list_active_projects actually ran.
#
# These tests pin the invariant that the guard cannot fire from a stray prefix
# match in a non-authority tool result. The full agent() integration path is
# exercised end-to-end in the smoke harness; here we document the contract
# the gate enforces.

def test_authority_override_invariant_documented():
    """The presentation contract is surfaced from the active-project payload.

    The deterministic reply replacements are gone — the agent composes the
    final wording from the payload (project rows + presentation contract).
    This test pins that the payload still carries the contract text the agent
    is told to follow and that its validation gates required-tool authority.
    """
    fake_active_project_output = (
        'ACTIVE_PROJECT_LOOKUP_JSON={"status":"matched","total":1,"projects":'
        '[{"id":"11111111-1111-4111-8111-111111111111","project":"Rorze","company":"Rorze"}],'
        '"safe_reply":"DỮ LIỆU DỰ ÁN từ tool — CHƯA phải câu trả lời."}\n'
        "SURFACED_PROJECT_IDS=id=11111111-1111-4111-8111-111111111111"
    )
    from app.graph.grounding import active_project_safe_reply

    assert active_project_safe_reply(fake_active_project_output) == (
        "DỮ LIỆU DỰ ÁN từ tool — CHƯA phải câu trả lời."
    )


def test_ground_reply_preserves_answer_when_no_authority_dispatched():
    """When list_active_projects was not dispatched, _ground_reply is the only path.

    A search_knowledge turn that happens to contain an ACTIVE_PROJECT_LOOKUP prefix
    somewhere in its (multi-line) output must NOT replace the LLM's reply.
    ``_ground_reply`` itself never replaces content on a prefix match — it only
    validates project-id hallucinations — so this test pins the no-replacement
    behavior that the gated override relies on.
    """
    search_knowledge_style_output = (
        "knowledge_chunks_result:\n"
        "Ca ngày: 08:00-20:00\nCa đêm: 20:00-08:00\n"
        'ACTIVE_PROJECT_LOOKUP_JSON={"status":"matched"}'  # stray line deep inside
    )
    grounded_reply = "LG Display làm ca ngày 08:00-20:00 và ca đêm 20:00-08:00."
    # _ground_reply never substitutes the reply based on a prefix match; only the
    # caller-level authority branches do, and those are now gated.
    assert _ground_reply(grounded_reply, [search_knowledge_style_output]) == grounded_reply
