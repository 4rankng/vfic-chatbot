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


# Header sentinel for the FAQ sheet's question column (NFC, lowercased). The
# parser requires this row so a malicious host returning arbitrary CSV-shaped
# rows cannot stage content-poisoning FAQs without matching the real sheet's
# shape (Finding 15).
_FAQ_HEADER_SENTINEL = unicodedata.normalize("NFC", "câu hỏi thường gặp").lower()
_STABLE_ID_MAX = 50


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


@register(KnowledgeCategoryKey.FAQ)
def parse_faq_csv(csv_text: str) -> dict[str, Any]:
    """Parse the LG Display FAQ sheet into a ``FaqDocument`` raw payload.

    Verified live-sheet shape: column A = section/category label, column B =
    question, column C = answer. Row 1 is the sheet title (A non-empty, B and C
    empty). Row 2 is the header (``Câu hỏi thường gặp``). Empty-A rows inherit
    the prior section label. Answers contain quoted commas and embedded newlines
    (handled natively by :mod:`csv`).

    Returns a dict with the exact keys ``FaqDocument`` accepts
    (``schema_version`` / ``category`` / ``faq``); each FAQ item has ``id`` /
    ``question`` / ``answer``. ``StrictModel(extra="forbid")`` rejects any other
    keys, so do not add ``faqs``/``q``/``a``.
    """
    # Strip a leading UTF-8 BOM defensively (Google Sheets exports include one).
    text = csv_text.lstrip(chr(0xFEFF))
    reader = csv.reader(io.StringIO(text))

    header_seen = False
    seen_ids: set[str] = set()
    faq_items: list[dict[str, Any]] = []

    for row in reader:
        # Pad short rows; column A/B/C are all we consume.
        cells = (row + ["", "", ""])[:3]
        category, question, answer = (_normalize(c) for c in cells)

        # Title row: a section/category label with no question or answer.
        if category and not question and not answer:
            continue
        # Header row (the live sheet's column-B label). Required before data so
        # a non-matching / poisoned sheet is rejected (Finding 15).
        if question.lower() == _FAQ_HEADER_SENTINEL:
            header_seen = True
            continue
        if not header_seen:
            raise ValueError("unexpected_header")
        # Section divider / blank: no question or no answer.
        if not question or not answer:
            continue
        item_id = _synthesize_id(question, seen_ids)
        seen_ids.add(item_id)
        faq_items.append({"id": item_id, "question": question, "answer": answer})

    # Canonical order: sort by (question, answer) so a cosmetic row reorder in
    # the sheet does not change the payload. Because the active revision is
    # staged from this same sorted output, its content_sha256 is over canonical
    # order too — so the orchestrator's hash-skip stays reorder-invariant without
    # diverging from revision.content_sha256 (Finding 11).
    faq_items.sort(key=lambda item: (item["question"], item["answer"]))
    return {"schema_version": "1.0", "category": "faq", "faq": faq_items}
