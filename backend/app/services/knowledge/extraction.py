"""Digest section chunker for the LLM training pipeline.

Uploads are assumed to be raw text (see ``KnowledgeService.upload_bytes``), so this
module no longer parses Office/PDF. It keeps only ``split_for_digest`` — the
boundary-aware splitter that bounds each digest LLM call to a sane input size
(the LLM does the real semantic splitting per section).

The splitter returns a :class:`DigestSections` struct so callers (the pipeline)
can observe whether the ``DIGEST_MAX_SECTIONS`` cap silently dropped content,
and report it via ``digest_meta`` rather than losing data without a trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.config import DIGEST_MAX_SECTIONS, DIGEST_SECTION_CHARS, DIGEST_SECTION_OVERLAP

if TYPE_CHECKING:
    from app.schemas.knowledge import ProjectTrainingPlan

# Boundary patterns used by ``_snap_boundary``. Paragraph wins over sentence,
# sentence over word; the hard char cut is the last-resort fallback.
# The CJK sentence pattern does NOT require trailing whitespace: CJK prose
# typically has no inter-sentence space, so we snap to the position immediately
# after the terminator itself (the Latin pattern requires the trailing space
# because Latin prose always has one).
_PARAGRAPH_BOUNDARY_RE = re.compile(r"\n\s*\n+")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_CJK_SENTENCE_BOUNDARY_RE = re.compile(r"[。！？]")
_WORD_BOUNDARY_RE = re.compile(r"\s+")

# Minimum chunk size we will shrink to when snapping backward; prevents the
# edge case where the first boundary is so close to ``start`` that we'd
# produce an empty or trivially-short chunk.
_MIN_CHUNK_CHARS = 64


@dataclass(frozen=True, slots=True)
class DigestSections:
    """Result of :func:`split_for_digest`.

    Attributes:
        sections: the chunks, each ``<= max_chars`` and snapped to a paragraph /
            sentence / word boundary where possible.
        truncated: ``True`` when the ``DIGEST_MAX_SECTIONS`` cap was hit and
            some source content could not be covered.
        dropped_chars: number of trailing source chars not covered by any
            section when ``truncated`` is ``True``; ``0`` otherwise.
        total_chars: length of the (stripped) input string.
    """

    sections: list[str]
    truncated: bool
    dropped_chars: int
    total_chars: int


def split_for_digest(text: str, max_chars: int | None = None) -> DigestSections:
    """Split long text into LLM-sized sections with overlap.

    The LLM does the real semantic splitting per section; this just keeps each
    call within a sane input size. Cut points prefer paragraph boundaries, then
    sentence boundaries, then word boundaries, then a hard character cut as a
    last resort — so Vietnamese diacritics and CJK sequences are not corrupted
    at the seam and the LLM receives clean, self-contained prose.

    The sliding window is computed explicitly so the tail is always covered
    (never silently dropped) and never duplicated (the off-by-one case where
    input length is just over a multiple of ``step``).
    """
    max_chars = max_chars or DIGEST_SECTION_CHARS
    overlap = DIGEST_SECTION_OVERLAP
    stripped = (text or "").strip()
    total = len(stripped)
    if total <= max_chars:
        return DigestSections([stripped] if stripped else [], False, 0, total)

    step = max(1, max_chars - overlap)
    sections: list[str] = []
    last_end = 0
    # Walk ideal window starts; cap the iteration at DIGEST_MAX_SECTIONS so a
    # runaway document cannot exhaust the RQ job budget.
    for index in range(DIGEST_MAX_SECTIONS):
        if last_end >= total:
            break
        # Ideal start for this window. We do NOT clamp backward to
        # ``total - max_chars``: that was the source of the duplicate-tail bug
        # (it forced the final window to overlap almost entirely with the
        # previous one). The natural ``min(start + max_chars, total)`` end +
        # boundary snap produces a short final chunk when appropriate, which is
        # the desired behavior.
        start = index * step if index == 0 else max(last_end - overlap, 0)
        if start >= total:
            break
        ideal_end = min(start + max_chars, total)
        end = _snap_boundary(stripped, ideal_end, start + _MIN_CHUNK_CHARS)
        chunk = stripped[start:end].strip()
        if chunk:
            sections.append(chunk)
        # Advance past the boundary so the next window starts after this chunk.
        last_end = end
        # Invariant: _snap_boundary returns >= min_end = start + _MIN_CHUNK_CHARS.
        assert end > start, "snap_boundary regressed: zero-progress chunk would loop"

    truncated = last_end < total
    dropped_chars = total - last_end if truncated else 0
    return DigestSections(sections, truncated, dropped_chars, total)


def _snap_boundary(text: str, ideal_end: int, min_end: int) -> int:
    """Return the largest end ``<= ideal_end`` that lands on a paragraph /
    sentence / word boundary; fall back to ``ideal_end`` if none exists in the
    allowed window.

    ``min_end`` protects against shrinking a chunk so far backward that it
    becomes empty or trivially short. The caller passes ``start + MIN_CHUNK_CHARS``
    so we always keep at least ``_MIN_CHUNK_CHARS`` of content even when the
    first boundary is very close to ``start``.
    """
    if ideal_end >= len(text) or ideal_end <= min_end:
        return ideal_end
    window = text[min_end:ideal_end]
    # Paragraph boundary (highest priority — cleanest cut for prose).
    matches = list(_PARAGRAPH_BOUNDARY_RE.finditer(window))
    if matches:
        # Position of the boundary start within ``text``.
        boundary = min_end + matches[-1].start()
        # Advance past the whitespace so the *next* chunk starts clean.
        return boundary if boundary > min_end else ideal_end
    # Sentence boundary — Latin (needs trailing whitespace).
    matches = list(_SENTENCE_BOUNDARY_RE.finditer(window))
    if matches:
        # Include the terminator with the current chunk; the trailing
        # whitespace starts the next chunk.
        boundary = min_end + matches[-1].start()
        return boundary if boundary > min_end else ideal_end
    # Sentence boundary — CJK (no trailing whitespace; snap to position after
    # the terminator so the current chunk keeps its terminating ``。``/``！``/``？``).
    matches = list(_CJK_SENTENCE_BOUNDARY_RE.finditer(window))
    if matches:
        boundary = min_end + matches[-1].end()
        return boundary if boundary > min_end else ideal_end
    # Word boundary.
    matches = list(_WORD_BOUNDARY_RE.finditer(window))
    if matches:
        boundary = min_end + matches[-1].start()
        return boundary if boundary > min_end else ideal_end
    # No boundary found in the window — hard cut. Caller's overlap covers it.
    return ideal_end


# --- Any-text category plan extraction ---------------------------------------
#
# "Nhập từ tệp văn bản" must accept ANY txt: when a file is neither a brief nor
# a category bundle, there is no deterministic structure to parse — the content
# has to be MAPPED into the twelve categories. That mapping is a judgment call,
# so it runs on the digest LLM through the existing ``json_extractor`` port and
# the result feeds the SAME training pipeline a parsed plan would.

_MAX_PLAN_EXTRACT_CHARS = 60_000


def _category_field_spec() -> str:
    """Human-readable record fields per category, straight from the models."""
    from app.project_knowledge.domain.category_catalog import (
        CATEGORY_DEFINITIONS,
    )
    from app.schemas.knowledge_categories import CATEGORY_DOCUMENT_MODELS
    from app.services.knowledge.category_markdown import _record_model

    lines: list[str] = []
    for definition in CATEGORY_DEFINITIONS:
        doc_model = CATEGORY_DOCUMENT_MODELS[definition.key]
        record_model = _record_model(doc_model, definition.list_field)
        fields = ", ".join(record_model.model_fields)
        lines.append(
            f"- {definition.key.value} ({definition.label_vi}): "
            f"mỗi record có các trường: {fields}"
        )
    return "\n".join(lines)


async def extract_category_plan(text: str, llm_json) -> "ProjectTrainingPlan | None":
    """Map arbitrary prose into category writes via the digest LLM.

    Returns ``None`` when the text carries no usable facts or extraction
    fails — callers fall back to plain document ingestion rather than erroring.
    """
    import json

    from app.project_knowledge.domain.category_catalog import (
        CATEGORY_DEFINITIONS,
    )
    from app.schemas.knowledge import ProjectTrainingPlan, ProjectTrainingWrite
    from app.services.knowledge.category_contracts import validate_category_payload
    from app.services.knowledge.category_markdown import build_source_markdown

    system = (
        "Chia nội dung phiếu thông tin sau vào các danh mục kiến thức tuyển dụng. "
        "Trả về JSON thuần (không markdown, không giải thích): object; mỗi khóa là "
        "MỘT tên danh mục tiếng Anh trong danh sách dưới đây (vd: jobs, contacts); "
        "giá trị là mảng record, mỗi record là object đúng các trường của danh mục đó. "
        "Chỉ đưa thông tin CÓ THẬT trong văn bản; danh mục không có dữ liệu thì bỏ "
        "khóa; tuyệt đối không bịa. Giữ nguyên số điện thoại/email/địa chỉ.\n\n"
        "Danh mục:\n" + _category_field_spec()
    )
    try:
        raw = await llm_json(system, text[:_MAX_PLAN_EXTRACT_CHARS])
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - extraction is best-effort by contract
        return None
    if not isinstance(data, dict):
        return None
    writes: list[ProjectTrainingWrite] = []
    for definition in CATEGORY_DEFINITIONS:
        records = data.get(definition.key.value)
        if not isinstance(records, list) or not records:
            continue
        payload = {
            "schema_version": "1.0",
            "category": definition.key.value,
            definition.list_field: [r for r in records if isinstance(r, dict)],
        }
        try:
            document = validate_category_payload(definition.key, payload)
        except Exception:  # noqa: BLE001 - one junk category skips, not fails
            continue
        writes.append(
            ProjectTrainingWrite(
                key=definition.key,
                filename=f"{definition.key.value}.md",
                content=build_source_markdown(document.model_dump(mode="json")) + "\n",
            )
        )
    if not writes:
        return None
    return ProjectTrainingPlan(writes=writes)
