"""Framework-free Vietnamese text normalization."""

from __future__ import annotations

import unicodedata


def normalize_vietnamese_text(value: str) -> str:
    """Return accent-insensitive, lowercased, whitespace-collapsed text."""

    no_marks = "".join(
        character
        for character in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(no_marks.replace("đ", "d").split())


__all__ = ["normalize_vietnamese_text"]
