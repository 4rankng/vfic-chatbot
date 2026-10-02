"""Answer-completion guard: repair a reply the provider cut at its output cap.

MiniMax M2.x cannot disable thinking and emits its deliberation *inside*
``content`` (`` thinking…``), so an operator-configured generation budget
(``llm_agent_max_tokens``, 0 = no cap and the shipped default) covers reasoning
AND answer. A cap the think block mostly consumes hands back a half-written
answer with ``finish_reason=length``; the reply boundary that used to repair a
cut answer was removed, so a cut would ship verbatim (observed: a route list
ending mid-word). The lanes therefore COMPLETE a cut answer before it is
delivered: the model is asked to continue from the exact cut, bounded by
``_MAX_ANSWER_CONTINUATIONS``. This recovery allowance remains available when
the normal tool-loop budget is exhausted; it cannot dispatch more tools. If
the provider still stops at the cap, one complete concise rewrite is attempted
over the same evidence. A capped or empty rewrite is suppressed, so a partial
list is never presented as a completed answer.

Pure text surgery plus a finish-reason read — no settings, no I/O — so both the
generation loop and the direct-context lane share one copy of the rules.
"""

from __future__ import annotations

import re

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
_SEAM_BOUNDARY_CHARS = frozenset(",.;:!?…-")
# A continuation sometimes re-opens with a sentence the answer already contains,
# glued to a fresh opener ("Dạ, em xin gửi..." restating "Em xin gửi..."), so the
# verbatim tail-seam check never matches. Sentences are compared case-folded and
# whitespace-collapsed; a leading span counts as restated when it is an earlier
# sentence, or when stripping the best-matching earlier sentence from it leaves
# less than a sentence's worth of new words behind (pure opener filler).
_SENTENCE_SPAN_RE = re.compile(r"[^.!?\n]*[.!?\n]+|[^.!?\n]+$")


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
    """Join the answer rounds of one generation, dropping a repeated seam.

    A continuation round either re-emits the tail it was handed (verbatim seam
    below) or re-opens the answer with a sentence from earlier in it behind a
    fresh opener — both are dropped, so the candidate reads each sentence once.
    """
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
    return _strip_restated_prefix(joined, part)


def _normalized(text: str) -> str:
    """Case-folded, whitespace-collapsed form used for restatement checks."""
    return " ".join(text.casefold().split())


def _sentence_spans(text: str) -> list[str]:
    """Sentence-ish spans of one round, delimiters and newlines kept attached."""
    return [m.group() for m in _SENTENCE_SPAN_RE.finditer(text) if m.group().strip()]


def _strip_restated_prefix(joined: str, part: str) -> str:
    """``part`` minus its leading run of sentences ``joined`` already contains.

    Only a LEADING run is dropped and the first sentence that says something new
    ends the scan, so repetition later in a continuation — which can be the
    model deliberately restating for emphasis — is never touched. A span also
    counts as restated when it merely wraps an earlier sentence in opener
    filler: what survives after removing the matched sentence must be shorter
    than a minimal contentful sentence, so a continuation that embeds an old
    sentence inside genuinely new prose keeps the new prose.
    """
    joined_norm = f" {_normalized(joined)} "
    restated = {
        s
        for s in (_normalized(span) for span in _sentence_spans(joined))
        if len(s) >= _CONTINUATION_OVERLAP_MIN_CHARS
    }
    kept_from = 0
    for span in _sentence_spans(part):
        span_norm = _normalized(span)
        if len(span_norm) < _CONTINUATION_OVERLAP_MIN_CHARS:
            break
        if f" {span_norm} " in joined_norm:
            kept_from += len(span)
            continue
        wrapped_leftover = None
        for sentence in restated:
            padded = f" {span_norm} "
            at = padded.find(f" {sentence} ")
            if at < 0:
                continue
            leftover = (padded[:at] + padded[at + len(sentence) + 2 :]).strip()
            if len(leftover) < _CONTINUATION_OVERLAP_MIN_CHARS:
                wrapped_leftover = leftover
                break
        if wrapped_leftover is None:
            break
        kept_from += len(span)
    return part[kept_from:]
