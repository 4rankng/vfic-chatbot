"""Digest section chunker for the LLM training pipeline.

Uploads are assumed to be raw text (see ``KnowledgeService.upload_bytes``), so this
module no longer parses Office/PDF. It keeps only ``split_for_digest`` — the naive
paragraph-aware splitter that bounds each digest LLM call to a sane input size
(the LLM does the real semantic splitting per section).
"""

from __future__ import annotations

from app.core.config import DIGEST_MAX_SECTIONS, DIGEST_SECTION_CHARS


def split_for_digest(text: str, max_chars: int | None = None) -> list[str]:
    """Naively split long text into LLM-sized sections with small overlap.

    The LLM does the real semantic splitting per section; this just keeps each call
    within a sane input size. Paragraph boundaries are respected where possible.
    """
    max_chars = max_chars or DIGEST_SECTION_CHARS
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    step = max(1, max_chars - 400)  # 400-char overlap
    sections: list[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + max_chars]
        if chunk.strip():
            sections.append(chunk)
        if start + max_chars >= len(text):
            break
        if len(sections) >= DIGEST_MAX_SECTIONS:
            break
    return sections
