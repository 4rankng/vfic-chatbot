"""Bounded source sections and resumable extraction of project category facts.

File decoding belongs to ``file_extraction``. Digest sections report source beyond
their provider-call budget so the pipeline can preserve it verbatim. Category
extraction requires complete source coverage, exact evidence and valid contracts
before returning a plan; budget exhaustion is an explicit failure.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.core.config import DIGEST_MAX_SECTIONS, DIGEST_SECTION_CHARS, DIGEST_SECTION_OVERLAP
from app.services.knowledge.category_plan_grounding import CategoryPlanExtractionError

logger = logging.getLogger(__name__)

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

CATEGORY_PLAN_VERSION = "category-plan-v2"
CATEGORY_PLAN_SECTION_CHARS = 12_000
CATEGORY_PLAN_MAX_SECTIONS = 200


def category_plan_sections(text: str) -> list[str]:
    """Cover the complete source with bounded, overlapping provider inputs."""
    source = text.strip()
    sections: list[str] = []
    start = 0
    overlap = min(DIGEST_SECTION_OVERLAP, CATEGORY_PLAN_SECTION_CHARS // 4)
    while start < len(source):
        if len(sections) >= CATEGORY_PLAN_MAX_SECTIONS:
            raise CategoryPlanExtractionError(
                "Source exceeds the category extraction section budget"
            )
        end = _snap_boundary(
            source,
            min(start + CATEGORY_PLAN_SECTION_CHARS, len(source)),
            start + CATEGORY_PLAN_SECTION_CHARS // 2,
        )
        sections.append(source[start:end])
        if end == len(source):
            break
        start = max(start + 1, end - overlap)
    return sections


def _category_field_spec() -> str:
    """Exact record contracts, including required fields, enums and nested data."""
    from app.project_knowledge.domain.category_catalog import (
        CATEGORY_DEFINITIONS,
    )
    from app.schemas.knowledge_categories import CATEGORY_DOCUMENT_MODELS
    from app.services.knowledge.category_markdown import _record_model

    lines: list[str] = []
    for definition in CATEGORY_DEFINITIONS:
        doc_model = CATEGORY_DOCUMENT_MODELS[definition.key]
        record_model = _record_model(doc_model, definition.list_field)
        schema = record_model.model_json_schema()
        schema["properties"].pop("id", None)
        schema["required"] = [name for name in schema.get("required", []) if name != "id"]
        lines.append(
            f"- {definition.key.value} ({definition.label_vi}): "
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )
    return "\n".join(lines)


async def extract_category_plan(
    text: str,
    llm_json: Callable[[str, str], Awaitable[str]],
    *,
    checkpoint: dict[str, Any] | None = None,
    on_checkpoint: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> "ProjectTrainingPlan | None":
    """Extract every section before returning one grounded category plan.

    ``None`` means the reviewed source has no category facts. Provider, schema,
    evidence, source-identity and coverage errors fail explicitly. Checkpoints
    retain validated evidence envelopes; replay validates them against the exact
    source before skipping any provider calls. The caller owns persistence and
    source/lease guards around the callback.
    """
    from app.project_knowledge.domain.category_catalog import (
        CATEGORY_DEFINITIONS,
    )
    from app.schemas.knowledge import ProjectTrainingPlan, ProjectTrainingWrite
    from app.services.knowledge.category_contracts import validate_category_payload
    from app.services.knowledge.category_markdown import (
        build_source_markdown,
        parse_category_markdown,
    )
    from app.services.knowledge.category_plan_grounding import (
        validate_category_envelope,
    )
    from app.services.knowledge.prompts import CATEGORY_PLAN_SYSTEM_PROMPT

    sections = category_plan_sections(text)
    keys = [definition.key.value for definition in CATEGORY_DEFINITIONS]
    source_checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
    completed: list[dict[str, Any]] = []
    dropped: list[tuple[str, str]] = []

    def validate_categories(data: Any, source: str) -> dict[str, Any]:
        """Keep every grounded record; drop the ones the source cannot support.

        One record with unverifiable evidence must not void the whole upload:
        the record is dropped (the operator sees its category in the "needs
        manual entry" list) and the rest of the file still trains. Nothing
        ungrounded is published either way.
        """
        if not isinstance(data, dict) or set(data) != set(keys):
            raise CategoryPlanExtractionError("Extraction must account for every project category")
        validated: dict[str, Any] = {}
        for key in keys:
            records = data[key]
            if not isinstance(records, list):
                raise CategoryPlanExtractionError("Category extraction is not a record list")
            accepted = []
            for record in records:
                try:
                    accepted.append(validate_category_envelope(key, record, source))
                except CategoryPlanExtractionError as exc:
                    dropped.append((key, str(exc)))
                    logger.info("category record rejected key=%s cause=%s", key, exc)
            validated[key] = accepted
        return validated

    if checkpoint is not None:
        if (
            checkpoint.get("version") != CATEGORY_PLAN_VERSION
            or checkpoint.get("source_sha256") != source_checksum
            or checkpoint.get("total_sections") != len(sections)
            or type(checkpoint.get("completed_sections")) is not int
            or not isinstance(checkpoint.get("sections"), list)
            or checkpoint["completed_sections"] != len(checkpoint["sections"])
            or not 0 <= checkpoint["completed_sections"] <= len(sections)
        ):
            raise CategoryPlanExtractionError("Extraction checkpoint does not match the source")
        for index, saved in enumerate(checkpoint["sections"]):
            if (
                not isinstance(saved, dict)
                or saved.get("index") != index
                or saved.get("source_sha256")
                != hashlib.sha256(sections[index].encode()).hexdigest()
            ):
                raise CategoryPlanExtractionError(
                    "Extraction checkpoint has incomplete source coverage"
                )
            completed.append(
                {
                    **saved,
                    "categories": validate_categories(saved.get("categories"), sections[index]),
                }
            )

    def state(status: str = "PROCESSING") -> dict[str, Any]:
        covered = [key for key in keys if any(section["categories"][key] for section in completed)]
        # Do not hand mutable internal state to caller-owned persistence hooks.
        return json.loads(
            json.dumps(
                {
                    "version": CATEGORY_PLAN_VERSION,
                    "source_sha256": source_checksum,
                    "total_sections": len(sections),
                    "completed_sections": len(completed),
                    "sections": completed,
                    "covered_categories": covered,
                    "missing_categories": [key for key in keys if key not in covered],
                    "status": status,
                }
            )
        )

    if on_checkpoint is not None:
        await on_checkpoint(state())
    system = CATEGORY_PLAN_SYSTEM_PROMPT.replace("{{CATEGORY_SCHEMAS}}", _category_field_spec())
    for index in range(len(completed), len(sections)):
        try:
            raw = await llm_json(system, sections[index])
        except Exception:
            raise CategoryPlanExtractionError(
                "Category extraction provider failed; retry the retained source"
            ) from None

        def unique_object(pairs):
            result = {}
            for name, value in pairs:
                if name in result:
                    raise CategoryPlanExtractionError("Category extraction returned invalid JSON")
                result[name] = value
            return result

        try:
            data = json.loads(raw, object_pairs_hook=unique_object)
        except (ValueError, TypeError):
            raise CategoryPlanExtractionError("Category extraction returned invalid JSON") from None
        validated = validate_categories(data, sections[index])
        completed.append(
            {
                "index": index,
                "source_sha256": hashlib.sha256(sections[index].encode()).hexdigest(),
                "categories": validated,
            }
        )
        if on_checkpoint is not None:
            await on_checkpoint(state())

    writes: list[ProjectTrainingWrite] = []
    for definition in CATEGORY_DEFINITIONS:
        records = {
            envelope["record"]["id"]: envelope["record"]
            for section in completed
            for envelope in section["categories"][definition.key.value]
        }
        if not records:
            continue
        payload = {
            "schema_version": "1.0",
            "category": definition.key.value,
            definition.list_field: list(records.values()),
        }
        try:
            document = validate_category_payload(definition.key, payload)
            markdown = build_source_markdown(document.model_dump(mode="json"))
            parse_category_markdown(definition.key, markdown)
        except ValueError:
            raise CategoryPlanExtractionError(
                "Combined category extraction exceeds its valid schema or size"
            ) from None
        writes.append(
            ProjectTrainingWrite(
                key=definition.key,
                filename=f"{definition.key.value}.md",
                content=markdown,
            )
        )
    if not writes and dropped:
        # Records were proposed but none could be grounded: that is a failed
        # mapping, not an empty source. Report it instead of importing nothing.
        raise CategoryPlanExtractionError("Extracted category records do not match the source")
    try:
        plan = ProjectTrainingPlan(writes=writes) if writes else None
    except ValueError:
        raise CategoryPlanExtractionError(
            "Combined category plan exceeds the training size budget"
        ) from None
    if on_checkpoint is not None:
        await on_checkpoint(state("COMPLETED"))
    return plan
