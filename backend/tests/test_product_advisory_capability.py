from app.capabilities.product_advisory import DESCRIPTOR
from app.capabilities.product_advisory.routing import route_product_advisory
from app.capabilities.product_advisory.tools import (
    UNSUPPORTED_LIVE_STATE_REPLY,
    product_advisory_preflight,
)


def test_product_advisory_is_document_grounded_and_rejects_live_commerce_claims():
    assert DESCRIPTOR.capability_id == "product_advisory"
    assert "stock" in DESCRIPTOR.unsupported_live_authority
    assert route_product_advisory("Sản phẩm này còn hàng không?") == "unsupported_live_state"
    assert route_product_advisory("Có sẵn không?") == "unsupported_live_state"
    assert route_product_advisory("Kiểm tra kho và giá bây giờ") == "unsupported_live_state"
    assert route_product_advisory("Có sẵn để chốt đơn không?") == "unsupported_live_state"
    assert route_product_advisory("Báo giá hôm nay giúp tôi") == "unsupported_live_state"
    assert route_product_advisory("Giao bao lâu và thanh toán thế nào?") == "unsupported_live_state"
    assert route_product_advisory("Hàng về chưa? Tôi muốn mua sản phẩm này") == "unsupported_live_state"
    assert route_product_advisory("Theo dõi đơn hàng, phí ship bao nhiêu?") == "unsupported_live_state"
    assert route_product_advisory("Có giao tận nơi không?") == "unsupported_live_state"
    assert route_product_advisory("Chính sách bảo hành là gì?") == "document_facts"
    assert product_advisory_preflight("Còn hàng không?") == UNSUPPORTED_LIVE_STATE_REPLY
    assert product_advisory_preflight("Chính sách bảo hành là gì?") is None
