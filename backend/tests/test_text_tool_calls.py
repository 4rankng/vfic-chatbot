"""A tool call the provider wrote as content is executed, never delivered.

Production evidence: one ``contact`` turn (09-26 09:44) recorded a single model
turn with ``tool_names=[]`` and shipped this bubble to the candidate —
``Dạ, để em kiểm tra thông tin liên hệ của VFIC ngay ạ.`` followed by
``<invoke name="search_knowledge">…``. The provider serialized its call into the
content, so nothing dispatched it and the markup became the answer.

The loop now parses that markup, dispatches it through the same guards as a
structured call, hands the result back to the model, and the boundary strips any
markup that survives.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.graph.runner import _finalize_user_visible_reply
from app.recruitment.domain.recommendation import ProjectFeatures

pytestmark = pytest.mark.timeout(30)

# The bubble production shipped verbatim (bot_run 1217, 09-26 09:44).
_LEAK = (
    "Dạ, để em kiểm tra thông tin liên hệ của VFIC ngay ạ.\n"
    '<invoke name="search_knowledge">\n'
    '<parameter name="query">hotline liên hệ VFIC</parameter>\n'
    "</invoke>"
)

# Same failure mode, on a tool whose double is one method.
_LIST_LEAK = (
    "Dạ, để em xem danh sách dự án đang tuyển ngay ạ.\n"
    '<invoke name="list_active_projects">\n'
    "</invoke>"
)


class _ScriptedLLM:
    """Returns scripted contents in order; no structured tool_calls."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.model_name = "scripted-model"
        self.trace_provider = "minimax"
        self.calls = 0

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def ainvoke(self, _messages, **_kwargs):
        from langchain_core.messages import AIMessage

        self.calls += 1
        content = self._contents.pop(0) if self._contents else ""
        return AIMessage(content=content)


class _FakeRetrieval:
    """Only ``list_active_projects`` is reachable, and it records its call."""

    def __init__(self) -> None:
        self.project_calls = 0

    async def list_active_projects(self):
        self.project_calls += 1
        return [ProjectFeatures(project_id="p1", slug="lg-display", name="LG Display")]


async def test_a_text_tool_call_is_dispatched_and_the_markup_never_ships():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    retrieval = _FakeRetrieval()
    llm = _ScriptedLLM([_LIST_LEAK, "Dạ, hiện có dự án LG Display đang tuyển ạ."])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)

    reply = await agent.agent(
        "có dự án nào đang tuyển?", system="sys", retrieval=retrieval, embedder=None
    )

    assert retrieval.project_calls == 1  # the text call really ran
    assert "<invoke" not in reply and "parameter" not in reply
    assert reply == "Dạ, hiện có dự án LG Display đang tuyển ạ."
    assert llm.calls == 2


async def test_an_unparsable_text_call_is_stripped_not_shipped():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    llm = _ScriptedLLM(['Dạ em kiểm tra ngay ạ. <invoke name=""> <parameter name="q">x'])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=3)

    reply = await agent.agent("x", system="sys", retrieval=_FakeRetrieval(), embedder=None)

    assert reply == "Dạ em kiểm tra ngay ạ. "
    assert "<invoke" not in reply


def test_the_converged_boundary_strips_markup_and_thinking():
    deps = SimpleNamespace()
    reply = _finalize_user_visible_reply(
        " thinkingcân nhắc</think>" + _LEAK,
        deps=deps,
        generated=True,
        user_text="hotline?",
        timings={},
        trace_sink=None,
    )
    assert reply.strip() == "Dạ, để em kiểm tra thông tin liên hệ của VFIC ngay ạ."
