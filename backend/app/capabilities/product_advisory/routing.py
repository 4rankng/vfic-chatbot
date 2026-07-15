"""Conservative product-advisory routing; live commerce claims always abstain."""

from __future__ import annotations

import re
import unicodedata


def _normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_marks.replace("đ", "d").replace("Đ", "d").casefold()


_LIVE_STATE = re.compile(
    r"\b("
    r"ton kho|kiem tra kho|inventory|con hang|het hang|san hang|con san|co san|co hang san|"
    r"hang ve chua|hang khi nao ve|"
    r"dat hang|dat mua|muon dat|muon mua|mua san pham|mua ngay|chot don|checkout|order|theo doi don|"
    r"thanh toan|tra tien|payment|"
    r"giao hang|van chuyen|ship|phi ship|cuoc ship|giao bao lau|giao tan noi|co giao duoc|"
    r"gia hien tai|gia hom nay|gia bay gio|gia luc nay|bao gia moi|price now"
    r")\b",
    re.I,
)


def route_product_advisory(text: str) -> str:
    """Return document_facts or unsupported_live_state without calling an LLM."""
    return "unsupported_live_state" if _LIVE_STATE.search(_normalise(text)) else "document_facts"
