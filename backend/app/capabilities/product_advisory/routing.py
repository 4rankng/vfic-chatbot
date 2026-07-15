"""Conservative product-advisory routing; live commerce claims always abstain."""

from __future__ import annotations

import re

_LIVE_STATE = re.compile(r"\b(tồn kho|còn hàng|đặt hàng|thanh toán|giao hàng|vận chuyển)\b", re.I)


def route_product_advisory(text: str) -> str:
    """Return document_facts or unsupported_live_state without calling an LLM."""
    return "unsupported_live_state" if _LIVE_STATE.search(text) else "document_facts"
