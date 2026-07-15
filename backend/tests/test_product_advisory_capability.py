from app.capabilities.product_advisory import DESCRIPTOR
from app.capabilities.product_advisory.routing import route_product_advisory


def test_product_advisory_is_document_grounded_and_rejects_live_commerce_claims():
    assert DESCRIPTOR.capability_id == "product_advisory"
    assert "stock" in DESCRIPTOR.unsupported_live_authority
    assert route_product_advisory("Sản phẩm này còn hàng không?") == "unsupported_live_state"
    assert route_product_advisory("Chính sách bảo hành là gì?") == "document_facts"
