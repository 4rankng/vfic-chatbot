"""Answer-completion guard: repair a reply the provider cut at its output cap.

MiniMax M2.x cannot disable thinking and emits its deliberation *inside*
``content`` (`` thinking…``), so an operator-configured generation budget
(``llm_agent_max_tokens``, 0 = no cap and the shipped default) covers reasoning
AND answer. A cap the think block mostly consumes hands back a half-written
answer with ``finish_reason=length``; the reply boundary that used to repair a
cut answer was removed, so a cut would ship verbatim (observed: a route list
ending mid-word). The lanes therefore COMPLETE a cut answer before it is
delivered: the model is asked to continue from the exact cut, bounded by
``_MAX_ANSWER_CONTINUATIONS`` and by the turn's remaining model-call budget. If
the provider still stops at the cap, the dangling tail is dropped (bounded to
the last complete sentence or line), so a candidate never receives a mid-word
fragment.

Pure text surgery plus a finish-reason read — no settings, no I/O — so both the
generation loop and the direct-context lane share one copy of the rules.
"""

from __future__ import annotations

_TRUNCATED_FINISH_REASONS = frozenset(
    {"length", "max_tokens", "max_output_tokens", "max_completion_tokens"}
)
_MAX_ANSWER_CONTINUATIONS = 2
_CUT_ANSWER_CONTINUE_INSTRUCTION = (
    "Câu trả lời của bạn vừa bị nhà cung cấp cắt ngang vì chạm hạn mức độ dài. "
    "Hãy viết tiếp NGAY tại đúng chỗ đang dở, không lặp lại phần đã viết, không mở "
    "đầu lại và không lặp lời chào; hoàn thành trọn vẹn câu trả lời cho người lao động."
)
# A repeated seam (the model re-emitting the tail it was handed) is dropped, but
# only when the overlap is long enough and word-aligned on both sides, so
# legitimate repetition inside an answer is never deleted.
_CONTINUATION_OVERLAP_MIN_CHARS = 24
_CONTINUATION_OVERLAP_MAX_CHARS = 400
_ANSWER_SENTENCE_END_CHARS = frozenset(".!?…")
_SEAM_BOUNDARY_CHARS = frozenset(",.;:!?…-")
# How far back a dangling (still-cut) tail may be trimmed, so a long complete
# answer is never gutted by a single missing full stop.
_MAX_DANGLING_TAIL_CHARS = 200


def _answer_was_cut(message) -> bool:
    """True when the provider stopped at its output cap instead of finishing."""
    metadata = getattr(message, "response_metadata", None) or {}
    reason = str(metadata.get("finish_reason") or metadata.get("stop_reason") or "")
    return reason.strip().lower() in _TRUNCATED_FINISH_REASONS


def _should_continue_cut_answer(message, visible: str, used: int) -> bool:
    """Whether a cut answer may be continued instead of shipped half-written."""
    return used < _MAX_ANSWER_CONTINUATIONS and bool(visible.strip()) and _answer_was_cut(message)


def _record_answer_continuation(metrics: dict | None, count: int) -> None:
    """Surface the output-cap repair on the turn's metrics."""
    if metrics is not None:
        metrics["answer_continuations"] = count
        metrics["answer_continuation_reason"] = "output_cap"


def _join_answer_parts(parts: list[str]) -> str:
    """Join the answer rounds of one generation, dropping a repeated seam."""
    joined = ""
    for part in parts:
        if not part:
            continue
        joined = part if not joined else joined + _seam_remainder(joined, part)
    return joined


def _seam_remainder(joined: str, part: str) -> str:
    """``part`` minus its overlap with ``joined``, else ``part`` unchanged."""
    limit = min(len(joined), len(part), _CONTINUATION_OVERLAP_MAX_CHARS)
    for size in range(limit, _CONTINUATION_OVERLAP_MIN_CHARS - 1, -1):
        if not joined.endswith(part[:size]):
            continue
        following = part[size : size + 1]
        if following and not (following.isspace() or following in _SEAM_BOUNDARY_CHARS):
            continue
        preceding = joined[-size - 1 : -size] if size < len(joined) else ""
        if preceding and not (preceding.isspace() or preceding in _SEAM_BOUNDARY_CHARS):
            continue
        return part[size:]
    return part


def _drop_dangling_tail(text: str) -> str:
    """Drop a still-truncated answer's dangling tail.

    Bounded to the last ``_MAX_DANGLING_TAIL_CHARS`` so a complete answer is
    never gutted: cut at the last sentence/line boundary in that window, else at
    the last whitespace, so the delivered text never ends mid-word.
    """
    stripped = text.rstrip()
    if not stripped:
        return text
    start = max(0, len(stripped) - _MAX_DANGLING_TAIL_CHARS)
    for index in range(len(stripped) - 1, start - 1, -1):
        if stripped[index] in _ANSWER_SENTENCE_END_CHARS or stripped[index] == "\n":
            return stripped[: index + 1].rstrip() or text
    for index in range(len(stripped) - 1, start - 1, -1):
        if stripped[index].isspace():
            return stripped[:index].rstrip() or text
    return text
