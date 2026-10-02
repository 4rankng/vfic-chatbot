"""Answer-completion guard — a cut generation never reaches a candidate.

MiniMax M2.x cannot disable thinking and emits its deliberation inside
``content`` (`` thinking…``), so the ``llm_agent_max_tokens`` generation budget
covers reasoning AND answer. A turn that hits it returns ``finish_reason=length``
with a half-written answer; the reply-policy layer that used to repair that was
removed on purpose, so the cut shipped verbatim (observed: a bus-route list
ending mid-word). These tests pin the replacement behaviour:

* a cut answer is continued from the exact cut and delivered complete;
* a provider that keeps stopping at the cap gets one complete rewrite over the
  same evidence, then suppression if it still cannot finish;
* a repeated seam is not duplicated;
* a normal ``finish_reason=stop`` answer is untouched and costs one call.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

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


async def test_answer_that_stays_cut_never_ships_an_incomplete_answer():
    """Exhausted continuations and an empty rewrite suppress the partial prose."""
    cut = (
        "Dạ bên em có các tuyến:\n"
        "- Tuyến Lạch Tray: Cầu vượt Lạch Tray (06:55) → Siêu thị Hà Cường (07:00)\n"
        "- Tuyến Hà Phươ"
    )
    llm = _CappedLLM([(cut, "length"), ("ng", "length"), (" thêm", "length")])
    metrics: dict = {}
    reply = await _run_agent(llm, metrics)

    assert reply == ""
    assert "Phươ" not in reply
    assert llm.calls == 4
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


async def test_continuation_restating_an_earlier_sentence_is_dropped():
    """The reported shape: a cut continuation re-opens with a mid-answer sentence.

    Round 1 was cut at the output cap; the continuation re-emitted an earlier
    sentence behind a fresh ``Dạ,`` opener. The verbatim tail-seam check cannot
    match that, so the restated-prefix check must drop the duplicate instead of
    shipping it a second time.
    """
    cut = (
        "Dạ, anh/chị muốn xin hotline để liên hệ trực tiếp ạ. "
        "Em xin gửi anh/chị số tổng đài miễn cước của VFIC: 1800 7228 ạ.\n\n"
        "Anh/chị gọi vào giờ hành chính sẽ gặp được nhân viên hỗ trợ tư vấn trực tiếp "
        "về dự án Rorze và các vị trí còn tuyển nhé ạ.\n\n"
        "Nếu anh/chị để lại số điện thoại di động, em sẽ nhờ chuyên viên chủ động gọi "
        "lại cho anh/chị, đỡ phải chờ máy ạ 😊"
    )
    llm = _CappedLLM(
        [
            (cut, "length"),
            ("Dạ, em xin gửi anh/chị số tổng đài miễn cước của VFIC: 1800 7228 ạ.", "stop"),
        ]
    )
    reply = await _run_agent(llm)

    assert reply == cut


async def test_restated_opener_dropping_keeps_the_continuation_new_content():
    """Only the restated leading run goes; genuinely new sentences stay."""
    cut = (
        "Dạ, anh/chị muốn xin hotline để liên hệ trực tiếp ạ. "
        "Em xin gửi anh/chị số tổng đài miễn cước của VFIC: 1800 7228 ạ.\n\n"
        "Anh/chị gọi vào giờ hành chính sẽ gặp được nhân viên hỗ trợ trực tiếp nhé ạ."
    )
    llm = _CappedLLM(
        [
            (cut, "length"),
            (
                "Dạ, em xin gửi anh/chị số tổng đài miễn cước của VFIC: 1800 7228 ạ. "
                "Ngoài ra anh/chị có thể để lại số điện thoại để em chủ động gọi lại ạ.",
                "stop",
            ),
        ]
    )
    reply = await _run_agent(llm)

    assert reply == cut + " Ngoài ra anh/chị có thể để lại số điện thoại để em chủ động gọi lại ạ."


async def test_repetition_after_new_continuation_content_is_kept():
    """A restated sentence that is NOT the leading run is never touched."""
    cut = (
        "Dạ, anh/chị muốn xin hotline để liên hệ trực tiếp ạ. "
        "Em xin gửi anh/chị số tổng đài miễn cước của VFIC: 1800 7228 ạ."
    )
    repeated = "Em xin gửi anh/chị số tổng đài miễn cước của VFIC: 1800 7228 ạ."
    llm = _CappedLLM(
        [
            (cut, "length"),
            (
                f"Về câu hỏi xin số máy lẻ của phòng tuyển dụng, em xin gửi lại ạ: {repeated}",
                "stop",
            ),
        ]
    )
    reply = await _run_agent(llm)

    assert reply == cut + f"Về câu hỏi xin số máy lẻ của phòng tuyển dụng, em xin gửi lại ạ: {repeated}"


async def test_normal_stop_answer_is_unchanged_and_costs_one_call():
    """A completed generation is never rewritten, and never continued."""
    llm = _CappedLLM([("Câu trả lời trọn vẹn cho người lao động.", "stop")])
    metrics: dict = {}
    reply = await _run_agent(llm, metrics)

    assert reply == "Câu trả lời trọn vẹn cho người lao động."
    assert llm.calls == 1
    assert "answer_continuations" not in metrics


async def test_last_normal_round_still_completes_the_capped_answer():
    """The tool-loop ceiling must not schedule a continuation that never runs."""
    from app.graph.clients import MiniMaxAgent

    cut = "Dạ có 5 dự án: LG Display, Rorze, Amtran, Kyocera và Pega"
    rest = "tron. Anh/chị muốn tìm hiểu dự án nào ạ?"
    llm = _CappedLLM([(cut, "length"), (rest, "stop")])
    metrics: dict = {}

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=1).agent(
        "cho tôi xem tất cả dự án",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=(),
        metrics=metrics,
    )

    assert reply == cut + rest
    assert llm.calls == 2
    assert metrics["answer_continuations"] == 1


async def test_completion_recovery_remains_bounded_after_the_last_normal_round():
    from app.graph.clients import MiniMaxAgent

    llm = _CappedLLM([
        ("Thông tin đã xác minh. Phần tiếp", "length"),
        (" theo vẫn", "length"),
        (" chưa hoàn", "length"),
        ("Thông tin vẫn chưa hoàn", "length"),
        (" tất", "stop"),
    ])
    metrics: dict = {}
    reply = await MiniMaxAgent(llm, embedder=None, max_iters=1).agent(
        "tư vấn giúp tôi",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=(),
        metrics=metrics,
    )

    assert llm.calls == 4
    assert metrics["answer_continuations"] == 2
    assert reply == ""
    assert metrics["answer_completion_failure"] == "output_cap_exhausted"


async def test_exhausted_continuations_rewrite_the_complete_answer_from_evidence():
    from app.graph.clients import MiniMaxAgent

    llm = _CappedLLM([
        ("Dạ có 5 dự án: LG Display và Rorze. Am", "length"),
        ("tran đang", "length"),
        (" tuyển tại", "length"),
        ("Dạ có LG Display, Rorze, Amtran, Kyocera và Pegatron ạ.", "stop"),
    ])
    metrics: dict = {}
    reply = await MiniMaxAgent(llm, embedder=None, max_iters=1).agent(
        "cho tôi xem tất cả dự án",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=(),
        metrics=metrics,
    )

    assert reply == "Dạ có LG Display, Rorze, Amtran, Kyocera và Pegatron ạ."
    assert llm.calls == 4
    assert metrics["answer_completion_rewrites"] == 1


async def test_rewrite_that_is_still_cut_suppresses_the_incomplete_list():
    from app.graph.clients import MiniMaxAgent

    llm = _CappedLLM([
        ("Dạ có 5 dự án: LG Display và Rorze. Am", "length"),
        ("tran đang", "length"),
        (" tuyển tại", "length"),
        ("Dạ có 5 dự án: LG Display, Rorze. Các dự", "length"),
        (" án khác", "stop"),
    ])
    metrics: dict = {}
    reply = await MiniMaxAgent(llm, embedder=None, max_iters=1).agent(
        "cho tôi xem tất cả dự án",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=(),
        metrics=metrics,
    )

    assert reply == ""
    assert llm.calls == 4
    assert metrics["answer_completion_failure"] == "output_cap_exhausted"


@pytest.mark.parametrize("wire_shape", ["structured", "text"])
async def test_completion_round_never_reenters_tool_dispatch(monkeypatch, wire_shape):
    from app.graph.clients import MiniMaxAgent
    from langchain_core.messages import AIMessage

    class ToolOnContinuation(_CappedLLM):
        async def ainvoke(self, messages, **kwargs):
            if not self.calls:
                return await super().ainvoke(messages, **kwargs)
            self.calls += 1
            if wire_shape == "structured":
                return AIMessage(content="", tool_calls=[{
                    "name": "list_active_projects", "args": {}, "id": "unexpected",
                }])
            return AIMessage(content='<invoke name="list_active_projects"></invoke>')

    dispatcher = AsyncMock(return_value="not-authorized")
    monkeypatch.setattr("app.graph.clients._dispatch_tool", dispatcher)
    model = ToolOnContinuation([("Thông tin đã xác minh. Câu chưa hoàn", "length")])
    metrics: dict = {}

    reply = await MiniMaxAgent(model, embedder=None, max_iters=2).agent(
        "cho tôi xem dự án", system="sys", retrieval=object(), embedder=None,
        allowed_tools=("list_active_projects",), metrics=metrics,
    )

    assert reply == ""
    assert dispatcher.await_count == 0
    assert model.calls == 2
    assert metrics["answer_completion_failure"] == "unexpected_tool_call"
