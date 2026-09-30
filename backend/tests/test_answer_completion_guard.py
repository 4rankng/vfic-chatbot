"""Answer-completion guard — a cut generation never reaches a candidate.

MiniMax M2.x cannot disable thinking and emits its deliberation inside
``content`` (`` thinking…``), so the ``llm_agent_max_tokens`` generation budget
covers reasoning AND answer. A turn that hits it returns ``finish_reason=length``
with a half-written answer; the reply-policy layer that used to repair that was
removed on purpose, so the cut shipped verbatim (observed: a bus-route list
ending mid-word). These tests pin the replacement behaviour:

* a cut answer is continued from the exact cut and delivered complete;
* a provider that keeps stopping at the cap has its dangling tail dropped, so
  no mid-word fragment is ever sent;
* a repeated seam is not duplicated;
* a normal ``finish_reason=stop`` answer is untouched and costs one call.
"""

from __future__ import annotations

import pytest

# The assertions observe call counts and delivered text; the timeout only guards
# against an event-loop hang.
pytestmark = pytest.mark.timeout(30)


class _CappedLLM:
    """Returns one scripted ``(text, finish_reason)`` round per model call."""

    def __init__(self, rounds: list[tuple[str, str]]) -> None:
        self._rounds = list(rounds)
        self.calls = 0
        self.messages: list = []
        self.model_name = "capped-model"
        self.trace_provider = "minimax"

    def bind_tools(self, tools, **_kwargs):  # noqa: ARG002
        return self

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        from langchain_core.messages import AIMessage

        text, reason = self._next(messages)
        return AIMessage(content=text, response_metadata={"finish_reason": reason})

    async def astream(self, messages, **kwargs):  # noqa: ARG002
        from langchain_core.messages import AIMessageChunk

        text, reason = self._next(messages)
        yield AIMessageChunk(content=text, response_metadata={"finish_reason": reason})

    def _next(self, messages) -> tuple[str, str]:
        self.calls += 1
        self.messages = messages
        return self._rounds.pop(0) if self._rounds else ("", "stop")


async def _run_agent(llm, metrics: dict | None = None, on_delta=None) -> str:
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    return await MiniMaxAgent(llm, embedder=None, max_iters=3).agent(
        "cho bằng xe buýt tới nhà máy",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=(),
        metrics=metrics,
        on_delta=on_delta,
    )


async def test_cut_answer_is_continued_and_delivered_complete():
    """A mid-word cut is completed by a continuation round, not shipped."""
    cut = (
        "Dạ bên em có các tuyến xe đưa đón đi LG Display như sau ạ:\n"
        "- Tuyến Lạch Tray: Cầu vượt Lạch Tray (06:55) → Siêu thị Hà Cường (07:00)\n"
        "- Tuyến Hà Phươ"
    )
    rest = "ng: Cầu vượt Hà Phượng (06:55) → Nhà máy LG Display (07:10)"
    deltas: list[str] = []

    async def _collect(text: str) -> None:
        deltas.append(text)

    llm = _CappedLLM([(cut, "length"), (rest, "stop")])
    metrics: dict = {}
    reply = await _run_agent(llm, metrics, on_delta=_collect)

    assert reply == cut + rest
    assert llm.calls == 2
    assert metrics["answer_continuations"] == 1
    assert metrics["answer_continuation_reason"] == "output_cap"
    # The continuation was requested with the cut answer in the transcript.
    assert any("cắt ngang" in str(getattr(message, "content", "")) for message in llm.messages)
    # The progressive stream stays the concatenation of both rounds.
    assert "".join(deltas) == cut + rest


async def test_answer_that_stays_cut_never_ships_a_mid_word_tail():
    """Exhausting the continuation budget drops the dangling tail instead."""
    cut = (
        "Dạ bên em có các tuyến:\n"
        "- Tuyến Lạch Tray: Cầu vượt Lạch Tray (06:55) → Siêu thị Hà Cường (07:00)\n"
        "- Tuyến Hà Phươ"
    )
    llm = _CappedLLM([(cut, "length"), ("ng", "length"), (" thêm", "length")])
    metrics: dict = {}
    reply = await _run_agent(llm, metrics)

    assert reply == (
        "Dạ bên em có các tuyến:\n"
        "- Tuyến Lạch Tray: Cầu vượt Lạch Tray (06:55) → Siêu thị Hà Cường (07:00)"
    )
    assert "Phươ" not in reply
    assert llm.calls == 3
    assert metrics["answer_continuations"] == 2


async def test_repeated_seam_is_not_duplicated():
    """A model that re-emits the tail it was handed does not double the text."""
    line = "- Tuyến TD Plaza: TD Plaza (06:55) → Vincom (07:10)"
    llm = _CappedLLM(
        [
            (f"Dạ bên em có các tuyến:\n{line}", "length"),
            (f"{line}\n- Tuyến Hà Phượng: Cầu vượt Hà Phượng (06:55) → Nhà máy (07:10)", "stop"),
        ]
    )
    reply = await _run_agent(llm)

    assert reply == (
        f"Dạ bên em có các tuyến:\n{line}\n"
        "- Tuyến Hà Phượng: Cầu vượt Hà Phượng (06:55) → Nhà máy (07:10)"
    )
    assert reply.count("TD Plaza: TD Plaza (06:55)") == 1


async def test_normal_stop_answer_is_unchanged_and_costs_one_call():
    """A completed generation is never rewritten, and never continued."""
    llm = _CappedLLM([("Câu trả lời trọn vẹn cho người lao động.", "stop")])
    metrics: dict = {}
    reply = await _run_agent(llm, metrics)

    assert reply == "Câu trả lời trọn vẹn cho người lao động."
    assert llm.calls == 1
    assert "answer_continuations" not in metrics
