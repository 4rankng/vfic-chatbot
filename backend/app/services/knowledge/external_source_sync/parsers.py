"""Per-category CSV→payload parsers for external-source sync.

A parser turns a fetched CSV document into the *raw payload dict* for one
:class:`~app.schemas.knowledge_categories.KnowledgeCategoryKey`. The payload is
the intermediate form; the orchestrator serialises it to canonical YAML and
validates it through ``parse_category_yaml`` so the result matches the category
pipeline's own contract exactly.

v1 ships the FAQ parser only (that is the live LG Display sheet). Adding a new
category later is a new ``@register(KnowledgeCategoryKey.X)`` function — the
registry isolates category-specific shape from the generic orchestrator.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.schemas.knowledge_categories import KnowledgeCategoryKey

# A parser maps the raw fetched text to the category's raw payload dict.
CategoryParser = Callable[[str], dict[str, Any]]

PARSERS: dict[KnowledgeCategoryKey, CategoryParser] = {}


def register(category_key: KnowledgeCategoryKey) -> Callable[[CategoryParser], CategoryParser]:
    def decorator(fn: CategoryParser) -> CategoryParser:
        PARSERS[category_key] = fn
        return fn

    return decorator


# Header sentinels for the FAQ sheet. NFC-normalised and lowercased so cosmetic
# Vietnamese diacritic variation or case does not defeat detection. The parser
# scans the header row for cells matching these, so it auto-detects column
# positions and survives the sheet owner inserting/removing/reordering prefix
# columns (Finding 15 poisoning defense preserved: a question header must still
# be present before any data row is accepted).
_FAQ_QUESTION_HEADERS = frozenset(
    unicodedata.normalize("NFC", s).lower()
    for s in ("câu hỏi thường gặp", "câu hỏi", "question", "questions")
)
_FAQ_ANSWER_HEADERS = frozenset(
    unicodedata.normalize("NFC", s).lower()
    for s in (
        "thông tin trả lời",
        "câu trả lời",
        "trả lời",
        "answer",
        "answers",
        "thông tin",
    )
)
# Optional category columns. ``section`` (e.g. ``STT theo quy trình``) is a
# grouping label inherited down blank cells; ``subcategory`` (e.g. ``Thông tin``)
# is a per-row topical tag. Both are sought only in columns BEFORE the question
# column, so they never collide with the answer header — the literal ``Thông
# tin`` is both a sub-category header and an answer-header sentinel, but the two
# live on opposite sides of the question column.
_FAQ_SECTION_HEADERS = frozenset(
    unicodedata.normalize("NFC", s).lower()
    for s in ("stt theo quy trình", "stt", "số thứ tự")
)
_FAQ_SUBCATEGORY_HEADERS = frozenset(
    unicodedata.normalize("NFC", s).lower()
    for s in ("thông tin", "nhóm", "chủ đề", "phân loại")
)
_STABLE_ID_MAX = 50
# Leading ordinal on a section label, e.g. "1. Thông tin trước khi phỏng vấn" →
# "Thông tin trước khi phỏng vấn". STT = số thứ tự (ordinal); the number is a
# sequence marker, not part of the category name, so it is stripped from tags.
_SECTION_ORDINAL_RE = re.compile(r"^\d+\.\s*")


def _normalize(text: str) -> str:
    """Strip + collapse internal whitespace + NFC-normalise Vietnamese."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).strip())


def _synthesize_id(question: str, seen: set[str]) -> str:
    """Slugify a question into a stable id; dedupe with a ``-N`` suffix.

    ASCII-folds after NFKD so Vietnamese letters (``đ`` and precomposed vowels
    that survive ``\\w``) never reach the id — the ``StableId`` regex only
    allows ``[A-Za-z0-9._-]``. Output always starts with an alphanumeric and is
    ≤50 chars, well under the 64-char ``StableId`` ceiling.
    """
    decomposed = unicodedata.normalize("NFKD", question).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9\s-]", "", decomposed.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")[:_STABLE_ID_MAX] or "faq"
    if not slug[0].isalnum():
        slug = "q" + slug
    candidate = slug
    n = 2
    while candidate in seen:
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


@dataclass(frozen=True, slots=True)
class _FaqColumns:
    """Resolved FAQ sheet column indices within the header row.

    ``section``/``subcategory`` are ``None`` when the sheet has no such column
    (the original 3-column layout has a subcategory column but no section
    column; a minimal Q/A-only sheet has neither).
    """

    question: int
    answer: int
    section: int | None = None
    subcategory: int | None = None


def _header_row_index(rows: list[list[str]]) -> int | None:
    """Index of the first row containing a question-column header cell."""
    for i, row in enumerate(rows):
        if any(_normalize(c).lower() in _FAQ_QUESTION_HEADERS for c in row):
            return i
    return None


def _detect_faq_columns(header: list[str]) -> _FaqColumns | None:
    """Resolve Q/A + optional category columns from the header row.

    Returns ``None`` if no question header is present. The answer column is the
    first answer-header cell AFTER the question column (defaulting to the next
    column). Section and sub-category columns are the first matching cells
    BEFORE the question column, so a prefix column whose header is neither (e.g.
    ``NewCol``/``Section`` in tests) is correctly ignored.
    """
    question_col = next(
        (i for i, c in enumerate(header) if _normalize(c).lower() in _FAQ_QUESTION_HEADERS),
        None,
    )
    if question_col is None:
        return None
    answer_col = question_col + 1
    for later_idx in range(question_col + 1, len(header)):
        if _normalize(header[later_idx]).lower() in _FAQ_ANSWER_HEADERS:
            answer_col = later_idx
            break
    section_col = next(
        (i for i in range(question_col) if _normalize(header[i]).lower() in _FAQ_SECTION_HEADERS),
        None,
    )
    subcategory_col = next(
        (
            i
            for i in range(question_col)
            if i != section_col and _normalize(header[i]).lower() in _FAQ_SUBCATEGORY_HEADERS
        ),
        None,
    )
    return _FaqColumns(question_col, answer_col, section_col, subcategory_col)


@register(KnowledgeCategoryKey.FAQ)
def parse_faq_csv(csv_text: str) -> dict[str, Any]:
    """Parse an FAQ Google Sheet into a ``FaqDocument`` raw payload.

    Auto-detects the question, answer, and optional category columns by scanning
    the header row for their sentinel cells (NFC-normalised, case-insensitive).
    This makes the parser robust to the sheet owner adding/removing/reordering
    prefix columns — the original 3-column layout (``Thông tin`` | Q | A) and the
    current 4-column LG Display layout (``STT theo quy trình`` | ``Thông tin`` |
    Q | A) parse identically.

    Two category columns are extracted as per-item ``tags``:

    * **section** (``STT theo quy trình``): a grouping label inherited down
      blank cells, with its leading ordinal stripped (``1. Thông tin trước khi
      phỏng vấn`` → ``Thông tin trước khi phỏng vấn``).
    * **subcategory** (``Thông tin``): a per-row topical tag. NOT inherited — a
      blank cell means no sub-category tag for that row.

    Rows before the header are skipped (sheet title, banner, etc.). Rows with an
    empty question or answer are skipped (but still update the inherited section
    if their section cell is non-empty). Answers may contain quoted commas and
    embedded newlines (handled natively by :mod:`csv`).

    Returns a dict with the exact keys ``FaqDocument`` accepts
    (``schema_version`` / ``category`` / ``faq``); each FAQ item has ``id`` /
    ``question`` / ``answer`` / ``tags``. ``StrictModel(extra="forbid")`` rejects
    any other keys, so do not add ``faqs``/``q``/``a``.

    Raises:
        ValueError: ``unexpected_header`` if no recognised question header row
            is found (preserves the Finding 15 content-poisoning defense).
    """
    # Strip a leading UTF-8 BOM defensively (Google Sheets exports include one).
    text = csv_text.lstrip(chr(0xFEFF))
    rows = list(csv.reader(io.StringIO(text)))

    header_index = _header_row_index(rows)
    if header_index is None:
        raise ValueError("unexpected_header")
    columns = _detect_faq_columns(rows[header_index])
    if columns is None:  # pragma: no cover — _header_row_index guarantees a hit
        raise ValueError("unexpected_header")
    question_col, answer_col, section_col, subcategory_col = (
        columns.question,
        columns.answer,
        columns.section,
        columns.subcategory,
    )

    seen_ids: set[str] = set()
    faq_items: list[dict[str, Any]] = []
    current_section: str | None = None  # inherited down blank section cells
    pad_to = max(question_col, answer_col, section_col or 0, subcategory_col or 0)

    for row in rows[header_index + 1 :]:
        # Pad short rows so indexing never raises (slice bounds the allocation).
        padded = (row + [""] * (pad_to + 1))[: pad_to + 1]
        # Section inheritance advances on ANY row whose section cell holds a real
        # label, including rows skipped below for missing Q/A (subsection
        # dividers). The leading ordinal (STT) is stripped — it is a sequence
        # marker, not a tag. A cell holding ONLY an ordinal (e.g. "2.") yields an
        # empty label after stripping and is treated as blank, so it does not
        # clobber the inherited section.
        if section_col is not None:
            section_text = _normalize(padded[section_col])
            if section_text:
                stripped_section = _SECTION_ORDINAL_RE.sub("", section_text)
                if stripped_section:
                    current_section = stripped_section
        question = _normalize(padded[question_col])
        answer = _normalize(padded[answer_col])
        # Blank / divider rows: no question or no answer.
        if not question or not answer:
            continue
        subcategory = (
            _normalize(padded[subcategory_col]) if subcategory_col is not None else ""
        )
        # Order: section (broad) → sub-category (specific); dedupe preserving order.
        tags = list(
            dict.fromkeys(tag for tag in (current_section, subcategory) if tag)
        )
        item_id = _synthesize_id(question, seen_ids)
        seen_ids.add(item_id)
        faq_items.append(
            {"id": item_id, "question": question, "answer": answer, "tags": tags}
        )

    # Canonical order: sort by (question, answer) so a cosmetic row reorder in
    # the sheet does not change the payload. Because the active revision is
    # staged from this same sorted output, its content_sha256 is over canonical
    # order too — so the orchestrator's hash-skip stays reorder-invariant without
    # diverging from revision.content_sha256 (Finding 11).
    faq_items.sort(key=lambda item: (item["question"], item["answer"]))
    return {"schema_version": "1.0", "category": "faq", "faq": faq_items}
