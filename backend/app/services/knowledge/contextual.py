"""Contextual Retrieval — a short document-context prefix per chunk at index time.

Anthropic's Contextual Retrieval (2024): chunks indexed in isolation lose the
document context that would make them retrievable — "Lương cơ bản 5.5 triệu"
retrieves poorly for "thu nhập LG Display thế nào?" because the embedding of
the bare chunk never mentions the document it belongs to. Prepending a 1-2
sentence context block before embedding recovered −49% failed retrievals
(−67% with rerank) on their evals.

Framework-first here: the prefix is built deterministically from metadata the
ingest path already has (document file name, digest summary, the unit's own
summary / source anchor / category). No extra LLM call at index time — the
digest step already produced the summarization a generated context would need.
Canonical-markdown documents are out of scope: their richer
``contextual_text`` header (:func:`app.services.knowledge.canonical.build_contextual_text`)
is part of the canonical document spec and already rides in their embed input.

The prefix never replaces data: ``content`` stays verbatim; the prefix rides
only in the embedding input and is recorded under ``metadata.contextual_prefix``
so a re-index can tell prefixed chunks from legacy ones
(``scripts/backfill_contextual_prefix.py`` relies on that marker).
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings

# Persisted under ``knowledge_chunks.metadata`` for every prefixed chunk. The
# backfill uses it as its idempotence marker and the benchmark gold-seeder
# mirrors the builder, so the version moves ONLY when the template changes in
# a way that changes embed inputs (then existing prefixes must be rebuilt).
CONTEXTUAL_PREFIX_VERSION = "ctx-v1"

# Bounds keep the prefix a *context* sentence, not a second document: the
# digest summary may itself be multi-sentence and the unit summary long.
_DOC_SUMMARY_MAX_CHARS = 220
_UNIT_SUMMARY_MAX_CHARS = 160
_PREFIX_MAX_CHARS = 600

# Human labels for the digest unit categories (coercion.CATEGORIES). Missing
# keys render nothing rather than a label-like guess.
_CATEGORY_LABELS_VI = {
    "job": "công việc/vị trí",
    "salary": "lương/thu nhập",
    "schedule": "lịch làm việc",
    "policy": "yêu cầu/quy định",
    "faq": "hỏi đáp",
    "contact": "kênh liên hệ",
    "benefits": "phúc lợi",
}


def contextual_enabled() -> bool:
    """Whether the env toggle ``rag_contextual_enabled`` is on (default)."""
    return bool(get_settings().rag_contextual_enabled)


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_chunk_context_prefix(
    *,
    doc_title: str | None,
    doc_summary: str | None = None,
    unit_summary: str | None = None,
    source_anchor: str | None = None,
    category: str | None = None,
) -> str | None:
    """Deterministic, metadata-first context sentence for one chunk.

    Assembles document title → digest summary → the unit's own summary, source
    anchor and topic label into one bounded sentence. Returns ``None`` when the
    metadata adds nothing beyond the chunk itself (no title, no summary at all)
    — embedding a bare label-only prefix would only dilute the vector.
    """
    title = _clip(doc_title, 200)
    summary = _clip(doc_summary, _DOC_SUMMARY_MAX_CHARS)
    unit = _clip(unit_summary, _UNIT_SUMMARY_MAX_CHARS)
    anchor = _clip(source_anchor, 80)
    topic = _CATEGORY_LABELS_VI.get(str(category or "").strip().lower(), "")

    sentences: list[str] = []
    if title:
        sentences.append(f"Tài liệu: {title}")
    if summary and summary != title:
        sentences.append(f"Tóm tắt tài liệu: {summary}")
    details: list[str] = []
    if unit:
        details.append(unit)
    if topic:
        details.append(f"chủ đề {topic}")
    if details:
        segment = f"Nội dung: {' — '.join(details)}"
        if anchor:
            segment += f" ({anchor})"
        sentences.append(segment)
    if not sentences:
        return None
    prefix = ". ".join(sentences) + "."
    if len(prefix) > _PREFIX_MAX_CHARS:
        prefix = prefix[: _PREFIX_MAX_CHARS - 1].rstrip() + "…"
    return prefix


def contextual_embed_input(
    unit: dict[str, Any],
    base_embed_text: str,
    *,
    doc_title: str | None,
    doc_summary: str | None = None,
) -> str:
    """Return the chunk's embed input with its context prefix prepended.

    Mutates nothing in ``base_embed_text``; when the toggle is off or the
    metadata yields no prefix the input is returned unchanged. Stamps
    ``unit["contextual_prefix"]`` (the persisted copy — see module docstring)
    so the caller can store it in chunk metadata alongside the verbatim
    content; cleared (set to ``None``) when no prefix applies.
    """
    if not contextual_enabled():
        unit["contextual_prefix"] = None
        return base_embed_text
    prefix = build_chunk_context_prefix(
        doc_title=doc_title,
        doc_summary=doc_summary,
        unit_summary=unit.get("summary"),
        source_anchor=unit.get("source_anchor"),
        category=unit.get("category"),
    )
    if not prefix:
        unit["contextual_prefix"] = None
        return base_embed_text
    unit["contextual_prefix"] = prefix
    return f"{prefix}\n{base_embed_text}"


__all__ = [
    "CONTEXTUAL_PREFIX_VERSION",
    "build_chunk_context_prefix",
    "contextual_embed_input",
    "contextual_enabled",
]
