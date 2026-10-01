"""Framework-free plain-text splitting without dropping factual content."""

from __future__ import annotations

import re

TEXT_BUBBLE_CHARS = 1600


def _append_split_part(parts: list[str], part: str) -> None:
    """Record one split unit, discarding anything that trims down to nothing.

    Every rung of the ladder funnels through here, so a blank separator (the
    gap between paragraphs, a stray newline, an exhausted segment) can never
    become a bubble of its own.
    """
    part = part.strip()
    if part:
        parts.append(part)


def _collect_word_fallbacks(piece: str, max_chars: int, parts: list[str]) -> None:
    """Third rung: pack a piece word by word, chopping any oversized word.

    A word is never broken across bubbles unless it cannot fit in one at all —
    then it is sliced into ``max_chars``-wide pieces so the provider cap still
    holds. Greedy packing keeps words whole: a word that would overflow the
    running segment closes the segment instead of being hyphenated into it.
    """
    segment = ""
    for word in piece.split():
        if len(word) > max_chars:
            _append_split_part(parts, segment)
            segment = ""
            for start in range(0, len(word), max_chars):
                _append_split_part(parts, word[start : start + max_chars])
            continue
        candidate = word if not segment else f"{segment} {word}"
        if len(candidate) <= max_chars:
            segment = candidate
            continue
        _append_split_part(parts, segment)
        segment = word
    _append_split_part(parts, segment)


def _collect_sentence_fallbacks(paragraph: str, max_chars: int, parts: list[str]) -> None:
    """Second rung: break an over-long paragraph on sentence or line ends."""
    for piece in re.split(r"(?<=[.!?。！？])\s+|\n+", paragraph):
        piece = piece.strip()
        if len(piece) <= max_chars:
            _append_split_part(parts, piece)
            continue
        _collect_word_fallbacks(piece, max_chars, parts)


def _collect_paragraphs(text: str, max_chars: int, parts: list[str]) -> None:
    """First rung: keep whole paragraphs; descend a rung when one is too long."""
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if len(paragraph) <= max_chars:
            _append_split_part(parts, paragraph)
            continue
        _collect_sentence_fallbacks(paragraph, max_chars, parts)


def _pack_parts(parts: list[str], max_chars: int) -> list[str]:
    """Re-glue the split parts into bubbles, blank-line separated and capped.

    Parts are already trimmed and non-empty (see ``_append_split_part``), so
    this pass only decides where a bubble ends: keep appending while the
    joined text fits, otherwise close the bubble and start the next one.
    """
    chunks: list[str] = []
    current = ""
    for part in parts:
        if not current:
            current = part
            continue
        candidate = f"{current}\n\n{part}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


def split_text_bubbles(
    text: str,
    max_chars: int = TEXT_BUBBLE_CHARS,
) -> list[str]:
    """Split plain text into bounded provider text bubbles without adding semantics.

    Nothing is dropped — only re-broken — so no word is lost or reordered.
    Coarse breaks are preferred: whole paragraphs, then sentences, then words.
    Only a word too wide for one bubble is cut at an arbitrary offset.
    Whitespace can normalize when long paragraphs descend to smaller units.
    Adjacent parts that still fit are re-joined into one bubble, so
    a short reply stays a single message rather than one per sentence.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    _collect_paragraphs(text, max_chars, parts)
    return _pack_parts(parts, max_chars)
