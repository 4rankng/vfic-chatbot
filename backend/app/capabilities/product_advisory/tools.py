"""Bounded product-advisory responses that do not require operational commerce data."""

from __future__ import annotations

from app.capabilities.product_advisory.routing import route_product_advisory

UNSUPPORTED_LIVE_STATE_REPLY = (
    "Tôi không thể xác nhận tình trạng còn hàng, giá hiện tại, đặt hàng, thanh toán hoặc giao nhận "
    "từ dữ liệu kiến thức. Vui lòng liên hệ kênh hỗ trợ của đơn vị để được xác nhận."
)


def product_advisory_preflight(text: str) -> str | None:
    """Return a safe handoff for live-state claims, otherwise permit document retrieval."""
    if route_product_advisory(text) == "unsupported_live_state":
        return UNSUPPORTED_LIVE_STATE_REPLY
    return None
