"""Internal starter packs. They map domain concepts; they are not standards claims.

These are deliberately document-owned schemas. Current inventory, prices, shipment
status, ETA, capacity, and live quotes belong to operational systems and are never
extracted as durable knowledge facts.
"""

RECRUITMENT_FACTORY = {
    "schema_version": "1",
    "record_types": [
        {
            "key": "job_posting",
            "display_name": "Job posting",
            "natural_key_fields": ["job_reference"],
            "scope_type": "job_posting",
            "scope_id_field": "job_reference",
            "fields": [
                {
                    "key": "job_reference",
                    "type": "string",
                    "aliases": ["mã việc làm", "job id"],
                    "required": True,
                },
                {
                    "key": "title",
                    "type": "string",
                    "aliases": ["vị trí", "chức danh"],
                    "required": True,
                },
                {
                    "key": "employer",
                    "type": "string",
                    "aliases": ["công ty", "nhà tuyển dụng"],
                    "required": False,
                },
                {
                    "key": "worksite",
                    "type": "string",
                    "aliases": ["nơi làm việc", "nhà máy"],
                    "required": False,
                },
                {
                    "key": "employment_type",
                    "type": "string",
                    "aliases": ["loại hợp đồng", "employment type"],
                    "required": False,
                },
            ],
        },
        {
            "key": "job_requirement",
            "display_name": "Job requirement",
            "natural_key_fields": ["job_reference", "requirement"],
            "scope_type": "job_posting",
            "scope_id_field": "job_reference",
            "fields": [
                {
                    "key": "job_reference",
                    "type": "string",
                    "aliases": ["mã việc làm", "job id"],
                    "required": True,
                },
                {
                    "key": "requirement",
                    "type": "string",
                    "aliases": ["yêu cầu", "requirement"],
                    "required": True,
                },
                {
                    "key": "priority",
                    "type": "enum",
                    "aliases": ["mức độ", "priority"],
                    "enum_values": ["essential", "optional"],
                    "required": False,
                },
                {
                    "key": "training",
                    "type": "string",
                    "aliases": ["đào tạo", "training"],
                    "required": False,
                },
            ],
        },
        {
            "key": "work_context",
            "display_name": "Work context and safety",
            "natural_key_fields": ["job_reference", "context"],
            "scope_type": "job_posting",
            "scope_id_field": "job_reference",
            "fields": [
                {
                    "key": "job_reference",
                    "type": "string",
                    "aliases": ["mã việc làm", "job id"],
                    "required": True,
                },
                {
                    "key": "context",
                    "type": "string",
                    "aliases": ["môi trường", "work context"],
                    "required": True,
                },
                {
                    "key": "equipment",
                    "type": "string",
                    "aliases": ["thiết bị", "equipment"],
                    "required": False,
                },
                {"key": "ppe", "type": "string", "aliases": ["bảo hộ", "ppe"], "required": False},
                {
                    "key": "hazard_note",
                    "type": "string",
                    "aliases": ["nguy cơ", "hazard"],
                    "required": False,
                },
            ],
        },
        {
            "key": "employment_policy",
            "display_name": "Employment policy",
            "natural_key_fields": ["job_reference", "policy"],
            "scope_type": "job_posting",
            "scope_id_field": "job_reference",
            "fields": [
                {
                    "key": "job_reference",
                    "type": "string",
                    "aliases": ["mã việc làm", "job id"],
                    "required": True,
                },
                {
                    "key": "policy",
                    "type": "string",
                    "aliases": ["chính sách", "policy"],
                    "required": True,
                },
                {
                    "key": "detail",
                    "type": "string",
                    "aliases": ["chi tiết", "detail"],
                    "required": False,
                },
                {
                    "key": "application_method",
                    "type": "string",
                    "aliases": ["cách ứng tuyển", "application method"],
                    "required": False,
                },
                {
                    "key": "transport_note",
                    "type": "string",
                    "aliases": ["đưa đón", "transport"],
                    "required": False,
                },
            ],
        },
    ],
}

SHOPPING_PRODUCT = {
    "schema_version": "1",
    "record_types": [
        {
            "key": "product",
            "display_name": "Product",
            "natural_key_fields": ["sku"],
            "fields": [
                {
                    "key": "sku",
                    "type": "string",
                    "aliases": ["sku", "mã sản phẩm"],
                    "required": True,
                },
                {
                    "key": "name",
                    "type": "string",
                    "aliases": ["tên", "tên sản phẩm"],
                    "required": True,
                },
                {"key": "material", "type": "string", "aliases": ["chất liệu"], "required": False},
                {
                    "key": "brand",
                    "type": "string",
                    "aliases": ["thương hiệu", "brand"],
                    "required": False,
                },
                {"key": "warranty", "type": "string", "aliases": ["bảo hành"], "required": False},
            ],
        },
        {
            "key": "product_variant",
            "display_name": "Product variant",
            "natural_key_fields": ["variant_sku"],
            "fields": [
                {
                    "key": "variant_sku",
                    "type": "string",
                    "aliases": ["sku biến thể", "variant sku"],
                    "required": True,
                },
                {
                    "key": "product_sku",
                    "type": "string",
                    "aliases": ["sku sản phẩm", "product sku"],
                    "required": True,
                },
                {
                    "key": "variant_name",
                    "type": "string",
                    "aliases": ["tên biến thể", "variant name"],
                    "required": True,
                },
                {
                    "key": "attributes",
                    "type": "string",
                    "aliases": ["thuộc tính", "attributes"],
                    "required": False,
                },
            ],
        },
        {
            "key": "document_offer",
            "display_name": "Document-owned offer",
            "natural_key_fields": ["offer_code"],
            "fields": [
                {
                    "key": "offer_code",
                    "type": "string",
                    "aliases": ["mã ưu đãi", "offer code"],
                    "required": True,
                },
                {
                    "key": "product_sku",
                    "type": "string",
                    "aliases": ["sku sản phẩm", "product sku"],
                    "required": False,
                },
                {
                    "key": "offer_terms",
                    "type": "string",
                    "aliases": ["điều kiện ưu đãi", "offer terms"],
                    "required": True,
                },
                {
                    "key": "valid_to",
                    "type": "date",
                    "aliases": ["hết hạn", "valid to"],
                    "required": False,
                },
            ],
        },
        {
            "key": "seller",
            "display_name": "Seller",
            "natural_key_fields": ["seller_code"],
            "fields": [
                {
                    "key": "seller_code",
                    "type": "string",
                    "aliases": ["mã người bán", "seller code"],
                    "required": True,
                },
                {
                    "key": "seller_name",
                    "type": "string",
                    "aliases": ["tên người bán", "seller name"],
                    "required": True,
                },
                {
                    "key": "seller_policy",
                    "type": "string",
                    "aliases": ["chính sách người bán", "seller policy"],
                    "required": False,
                },
            ],
        },
        {
            "key": "promotion",
            "display_name": "Promotion",
            "natural_key_fields": ["promotion_code"],
            "fields": [
                {
                    "key": "promotion_code",
                    "type": "string",
                    "aliases": ["mã khuyến mãi", "promotion code"],
                    "required": True,
                },
                {
                    "key": "promotion_terms",
                    "type": "string",
                    "aliases": ["điều kiện khuyến mãi", "promotion terms"],
                    "required": True,
                },
                {
                    "key": "valid_to",
                    "type": "date",
                    "aliases": ["hết hạn khuyến mãi", "promotion valid to"],
                    "required": False,
                },
            ],
        },
        {
            "key": "warranty_return",
            "display_name": "Warranty and returns",
            "natural_key_fields": ["policy_code"],
            "fields": [
                {
                    "key": "policy_code",
                    "type": "string",
                    "aliases": ["mã chính sách", "policy code"],
                    "required": True,
                },
                {
                    "key": "product_sku",
                    "type": "string",
                    "aliases": ["sku sản phẩm", "product sku"],
                    "required": False,
                },
                {
                    "key": "warranty",
                    "type": "string",
                    "aliases": ["bảo hành chính sách", "policy warranty"],
                    "required": False,
                },
                {
                    "key": "return_policy",
                    "type": "string",
                    "aliases": ["đổi trả", "return policy"],
                    "required": True,
                },
            ],
        },
    ],
}

LOGISTICS_SERVICE = {
    "schema_version": "1",
    "record_types": [
        {
            "key": "transport_service",
            "display_name": "Transport service",
            "natural_key_fields": ["service_code"],
            "fields": [
                {
                    "key": "service_code",
                    "type": "string",
                    "aliases": ["mã dịch vụ", "service code"],
                    "required": True,
                },
                {
                    "key": "service_name",
                    "type": "string",
                    "aliases": ["tên dịch vụ"],
                    "required": True,
                },
                {
                    "key": "service_description",
                    "type": "string",
                    "aliases": ["mô tả dịch vụ", "service description"],
                    "required": False,
                },
            ],
        },
        {
            "key": "lane",
            "display_name": "Service lane",
            "natural_key_fields": ["lane_code"],
            "fields": [
                {
                    "key": "lane_code",
                    "type": "string",
                    "aliases": ["mã tuyến", "lane code"],
                    "required": True,
                },
                {
                    "key": "origin",
                    "type": "string",
                    "aliases": ["điểm đi", "origin"],
                    "required": True,
                },
                {
                    "key": "destination",
                    "type": "string",
                    "aliases": ["điểm đến", "destination"],
                    "required": True,
                },
            ],
        },
        {
            "key": "facility",
            "display_name": "Facility",
            "natural_key_fields": ["facility_code"],
            "fields": [
                {
                    "key": "facility_code",
                    "type": "string",
                    "aliases": ["mã cơ sở", "facility code"],
                    "required": True,
                },
                {
                    "key": "facility_name",
                    "type": "string",
                    "aliases": ["tên cơ sở", "facility name"],
                    "required": True,
                },
                {
                    "key": "facility_type",
                    "type": "string",
                    "aliases": ["loại cơ sở", "facility type"],
                    "required": False,
                },
            ],
        },
        {
            "key": "vehicle_capability",
            "display_name": "Vehicle capability",
            "natural_key_fields": ["capability_code"],
            "fields": [
                {
                    "key": "capability_code",
                    "type": "string",
                    "aliases": ["mã năng lực", "capability code"],
                    "required": True,
                },
                {
                    "key": "vehicle_type",
                    "type": "string",
                    "aliases": ["loại xe", "vehicle type"],
                    "required": True,
                },
                {
                    "key": "capability_description",
                    "type": "string",
                    "aliases": ["mô tả năng lực", "capability description"],
                    "required": False,
                },
            ],
        },
        {
            "key": "rate_card",
            "display_name": "Document-owned rate card",
            "natural_key_fields": ["rate_code"],
            "fields": [
                {
                    "key": "rate_code",
                    "type": "string",
                    "aliases": ["mã bảng giá", "rate code"],
                    "required": True,
                },
                {
                    "key": "lane_code",
                    "type": "string",
                    "aliases": ["mã tuyến bảng giá", "rate lane code"],
                    "required": True,
                },
                {
                    "key": "rate_rule",
                    "type": "string",
                    "aliases": ["quy tắc giá", "rate rule"],
                    "required": True,
                },
                {
                    "key": "valid_to",
                    "type": "date",
                    "aliases": ["hết hạn", "valid to"],
                    "required": False,
                },
            ],
        },
    ],
}

STARTER_PACKS = {
    "recruitment_factory": RECRUITMENT_FACTORY,
    "shopping_product": SHOPPING_PRODUCT,
    "logistics_service": LOGISTICS_SERVICE,
}
