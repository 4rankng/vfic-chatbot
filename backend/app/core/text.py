"""Shared Vietnamese text normalization utilities."""
from __future__ import annotations

import unicodedata


def normalize_vietnamese_text(value: str) -> str:
    """Accent-insensitive, lowercased, whitespace-collapsed Vietnamese text.

    NFD-decomposes, strips combining marks (Mn category), replaces đ→d,
    and collapses whitespace.  Used for dedup keys, lexical term extraction,
    and search normalization throughout the codebase.
    """
    no_marks = "".join(
        ch
        for ch in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(ch) != "Mn"
    )
    no_marks = no_marks.replace("đ", "d")
    return " ".join(no_marks.split())
