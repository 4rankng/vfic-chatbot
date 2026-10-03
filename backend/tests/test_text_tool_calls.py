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
from app.graph.think_strip import (
    contains_tool_protocol,
    extract_text_tool_calls,
    strip_provider_artifacts,
)
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

# U+FF5C FULLWIDTH VERTICAL LINE is what the provider used to close the
# namespace tag when it wrote the 2026-10-03 call into the content; only the
# ASCII form was recognised before, so nothing dispatched it and the markup
# became the bubble. Written as escapes on purpose: the byte sequence is copied
# from the production leak pinned in ``test_graph_think_strip.py``, and it is
# not worth a typo.
_FWB = "\uff5c"


def _ns(tag: str) -> str:
    """Wrap a tag body in the fullwidth-bar namespace production emitted."""
    return f"<{_FWB}DSML{_FWB} {tag}>"


# The bubble production delivered (11:01 turn), close tags included: without the
# balanced close tag the parser finds no block and the call is never dispatched.
_DSML_LEAK = (
    _ns("calls")
    + "\n"
    + _ns('invoke name="get_project_distance"')
    + "\n"
    + _ns('parameter name="location" string="true"')
    + "312 Nguyen Cong Hoa, Hai An, Hai Phong"
    + f"</{_FWB}DSML{_FWB} parameter>\n"
    + _ns('parameter name="company" string="true"')
    + "amtran"
    + f"</{_FWB}DSML{_FWB} parameter>\n"
    + f"</{_FWB}DSML{_FWB} invoke>\n"
    + f"</{_FWB}DSML{_FWB} calls>"
)

# The same serialization on the one tool ``_FakeRetrieval`` exposes, so the loop
# test can prove the call really ran.
_DSML_LEAK_LOOKUP = (
    _ns("calls")
    + "\n"
    + _ns('invoke name="list_active_projects"')
    + "\n"
    + f"</{_FWB}DSML{_FWB} invoke>\n"
    + f"</{_FWB}DSML{_FWB} calls>"
)

# A serialization no parser knows: the detector must still recognise it (pinned
# in ``test_graph_think_strip.py``), and the loop must retry rather than ship it.
_RESIDUE = "<|spiral|>warp drive=1> tra cứu"


class _ScriptedLLM:
    """Returns scripted contents in order; no structured tool_calls."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.model_name = "scripted-model"
        self.calls = 0
        # The message list of every round, so a test can assert protocol shape
        # (which assistant message a ToolMessage answers).
        self.seen: list[list] = []

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def ainvoke(self, messages, **_kwargs):
        from langchain_core.messages import AIMessage

        self.seen.append(list(messages))
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


def test_the_dsml_leak_parses_with_its_arguments_and_strips_clean():
    """The close-tag form is load-bearing: a block without it parses to nothing."""
    calls = extract_text_tool_calls(_DSML_LEAK)

    assert len(calls) == 1
    assert calls[0]["name"] == "get_project_distance"
    assert calls[0]["args"] == {
        "location": "312 Nguyen Cong Hoa, Hai An, Hai Phong",
        "company": "amtran",
    }

    stripped = strip_provider_artifacts(_DSML_LEAK)
    assert "get_project_distance" not in stripped
    assert "<" not in stripped


async def test_a_dsml_text_tool_call_is_dispatched_and_the_result_forms_the_answer():
    """The 2026-10-03 serialization, end to end: dispatch, then a second round.

    Round 2 is the proof the model answered from the tool result rather than the
    turn failing on a tool-role message no assistant message declares.
    """
    pytest.importorskip("langchain_core")
    from langchain_core.messages import ToolMessage

    from app.graph.clients import MiniMaxAgent

    retrieval = _FakeRetrieval()
    llm = _ScriptedLLM([_DSML_LEAK_LOOKUP, "Dạ, hiện có dự án LG Display đang tuyển ạ."])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)

    reply = await agent.agent(
        "có dự án nào đang tuyển?", system="sys", retrieval=retrieval, embedder=None
    )

    assert retrieval.project_calls == 1  # the text call really ran
    assert llm.calls == 2
    assert "invoke" not in reply and "DSML" not in reply
    assert reply == "Dạ, hiện có dự án LG Display đang tuyển ạ."

    # Protocol shape: every tool-role message answers an assistant message that
    # declares the matching tool_call id and carries no markup. This is what an
    # OpenAI-compatible endpoint validates on the next round; without the
    # normalization it rejects the request.
    round_two = llm.seen[1]
    answered = 0
    for index, message in enumerate(round_two):
        if not isinstance(message, ToolMessage):
            continue
        declared = round_two[index - 1]
        assert declared.tool_calls, round_two
        assert declared.tool_calls[0]["id"] == message.tool_call_id
        assert "invoke" not in str(declared.content)
        assert "DSML" not in str(declared.content)
        answered += 1
    assert answered == 1


async def test_protocol_residue_gets_one_retry_then_a_clean_answer():
    """Residue is not a reply, but it is also not the model's fault: retry once."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    retrieval = _FakeRetrieval()
    llm = _ScriptedLLM([_RESIDUE, "Dạ, em chưa có thông tin ạ."])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)

    reply = await agent.agent("x", system="sys", retrieval=retrieval, embedder=None)

    assert llm.calls == 2  # the round was spent again, not suppressed
    assert reply == "Dạ, em chưa có thông tin ạ."
    assert retrieval.project_calls == 0


async def test_protocol_residue_twice_suppresses_instead_of_leaking():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    llm = _ScriptedLLM([_RESIDUE, _RESIDUE])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)

    reply = await agent.agent("x", system="sys", retrieval=_FakeRetrieval(), embedder=None)

    assert reply == ""


def test_the_converged_boundary_strips_markup_and_thinking():
    deps = SimpleNamespace()
    reply = _finalize_user_visible_reply(
        " thinkingcân nhắc</think>" + _LEAK,
        deps=deps,
        generated=True,
        user_text="hotline?",
        timings={},
    )
    assert reply.strip() == "Dạ, để em kiểm tra thông tin liên hệ của VFIC ngay ạ."


def test_the_converged_boundary_refuses_protocol_residue_it_cannot_strip():
    """A miss by the stripper must not reach a candidate; curated text is exempt."""
    deps = SimpleNamespace()
    assert contains_tool_protocol(_RESIDUE)

    assert (
        _finalize_user_visible_reply(
            _RESIDUE, deps=deps, generated=True, user_text="hotline?", timings={}
        )
        == ""
    )
    # ``generated=False`` is DB-authored content: angle brackets there are the
    # operator's, not the provider's.
    assert (
        _finalize_user_visible_reply(
            _RESIDUE, deps=deps, generated=False, user_text="hotline?", timings={}
        )
        == _RESIDUE
    )
