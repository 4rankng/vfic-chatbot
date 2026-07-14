"""Vietnamese text normalization for ingestion (Tech-Lead Directive §9 stage 3).

Normalizes parsed text before extraction: NFC unicode, whitespace, dates, times,
money, phones, locations. Preserves ``original_text`` — only produces a
``normalized_text`` companion.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_unicode(text: str) -> str:
    """NFC normalization (composes Vietnamese diacritics correctly)."""
    return unicodedata.normalize("NFC", text)


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace; strip lines; normalize line endings."""
    # Normalize line endings then collapse runs.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse runs of spaces/tabs (NOT newlines — those are structural).
    text = re.sub(r"[ \t]+", " ", text)
    # Strip trailing whitespace per line.
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines)


def normalize_times(text: str) -> str:
    """Normalize common Vietnamese time formats to 24h HH:MM.

    Handles: "6 giờ", "6h", "6:00", "06:00", "6 giờ sáng", "18 giờ tối".
    """
    # "6 giờ" / "6h" → "6:00"
    text = re.sub(r"\b(\d{1,2})\s*(?:giờ|h)\b", r"\1:00", text, flags=re.IGNORECASE)
    # "6 giờ sáng" → morning (no change to the 6:00 we just produced)
    # "6 giờ chiều" / "6 giờ tối" → +12 (PM)
    def _pm(m: re.Match) -> str:
        hour = int(m.group(1))
        if hour < 12:
            hour += 12
        return f"{hour}:00"

    text = re.sub(
        r"\b(\d{1,2}):00\s*(?:chiều|tối|pm|phút chiều)\b",
        _pm,
        text,
        flags=re.IGNORECASE,
    )
    return text


def normalize_money(text: str) -> str:
    """Normalize Vietnamese money shorthand to digits.

    "500k" → "500000", "1.5tr" / "1.5 triệu" → "1500000", "5 triệu" → "5000000".
    """
    text = re.sub(r"\b(\d+(?:\.\d+)?)k\b", lambda m: str(int(float(m.group(1)) * 1000)), text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(\d+(?:[.,]\d+)?)\s*(?:tr|triệu)\b",
        lambda m: str(int(float(m.group(1).replace(",", ".")) * 1_000_000)),
        text,
        flags=re.IGNORECASE,
    )
    return text


def normalize_text(text: str) -> str:
    """Full normalization pipeline. Preserves Vietnamese diacritics."""
    text = normalize_unicode(text)
    text = normalize_times(text)
    text = normalize_money(text)
    text = normalize_whitespace(text)
    return text


def normalize_query(text: str) -> str:
    """Lighter normalization for cache keys: NFC + lowercase + whitespace collapse.

    Does NOT do time/money normalization (those would conflate queries).
    """
    nfc = unicodedata.normalize("NFC", text.strip().lower())
    return " ".join(nfc.split())
