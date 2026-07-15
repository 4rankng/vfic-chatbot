import pytest

from app.services.ingestion.reference_templates import (
    LOGISTICS_SERVICE,
    RECRUITMENT_FACTORY,
    SHOPPING_PRODUCT,
)
from app.services.ingestion.template_compiler import TemplateCompileError, compile_template
from app.services.ingestion.template_ingestion import TemplateIngestionService


def test_compiler_is_deterministic_for_starter_pack():
    artifact_a, checksum_a = compile_template(SHOPPING_PRODUCT)
    artifact_b, checksum_b = compile_template(SHOPPING_PRODUCT)

    assert artifact_a == artifact_b
    assert checksum_a == checksum_b
    assert artifact_a["compiler_version"] == "1"


def test_compiler_v2_supports_bounded_repeated_and_tabular_occurrences():
    definition = {
        "schema_version": "2",
        "record_types": [
            {
                "key": "product",
                "display_name": "Product",
                "occurrence_mode": "table_rows",
                "max_records": 500,
                "natural_key_fields": ["sku"],
                "fields": [
                    {"key": "sku", "type": "string", "aliases": ["SKU"]},
                    {"key": "name", "type": "string", "aliases": ["Tên"]},
                ],
            }
        ],
    }

    artifact, _ = compile_template(definition)

    assert artifact["compiler_version"] == "2"
    assert artifact["record_types"][0]["occurrence_mode"] == "table_rows"
    assert artifact["record_types"][0]["max_records"] == 500


@pytest.mark.parametrize(
    "definition",
    [
        {
            "schema_version": "1",
            "record_types": [
                {
                    "key": "legacy",
                    "display_name": "Legacy",
                    "occurrence_mode": "table_rows",
                    "natural_key_fields": ["id"],
                    "fields": [{"key": "id", "type": "string"}],
                }
            ],
        },
        {
            "schema_version": "2",
            "record_types": [
                {
                    "key": "single",
                    "display_name": "Single",
                    "max_records": 2,
                    "natural_key_fields": ["id"],
                    "fields": [{"key": "id", "type": "string"}],
                }
            ],
        },
    ],
)
def test_compiler_rejects_invalid_occurrence_bounds(definition):
    with pytest.raises(TemplateCompileError):
        compile_template(definition)


@pytest.mark.parametrize(
    ("definition", "expected_record_types"),
    [
        (
            SHOPPING_PRODUCT,
            {"product", "product_variant", "document_offer", "seller", "promotion", "warranty_return"},
        ),
        (
            LOGISTICS_SERVICE,
            {"transport_service", "lane", "facility", "vehicle_capability", "rate_card"},
        ),
        (
            RECRUITMENT_FACTORY,
            {"job_posting", "job_requirement", "work_context", "employment_policy"},
        ),
    ],
)
def test_starter_packs_compile_with_declared_domain_coverage(definition, expected_record_types):
    artifact, _ = compile_template(definition)
    assert {record["key"] for record in artifact["record_types"]} == expected_record_types


def test_compiler_requires_scope_identity_for_non_global_records():
    definition = {
        "schema_version": "1",
        "record_types": [{
            "key": "scoped",
            "display_name": "Scoped",
            "scope_type": "job_posting",
            "natural_key_fields": ["id"],
            "fields": [{"key": "id", "type": "string"}],
        }],
    }
    with pytest.raises(TemplateCompileError):
        compile_template(definition)


@pytest.mark.parametrize(
    "definition",
    [
        {"schema_version": "1", "record_types": []},
        {"schema_version": "1", "record_types": [{"key": "prompt", "display_name": "bad", "fields": [], "natural_key_fields": []}]},
        {"schema_version": "1", "record_types": [{"key": "safe", "display_name": "safe", "fields": [{"key": "sql", "type": "string"}], "natural_key_fields": ["sql"]}]},
    ],
)
def test_compiler_rejects_unsafe_or_empty_definitions(definition):
    with pytest.raises(TemplateCompileError):
        compile_template(definition)


async def test_preview_extracts_only_source_backed_fields():
    artifact, _ = compile_template(LOGISTICS_SERVICE)
    service = TemplateIngestionService(None)  # type: ignore[arg-type]

    records, issues = service._extract_artifact(
        artifact,
        "Mã dịch vụ: TRUCK-01\nTên dịch vụ: Hàng nguyên chuyến\nNăng lực xe: 15 tấn",
        file_id=None,
    )

    assert records[0]["payload"]["service_code"] == "TRUCK-01"
    assert records[0]["payload"]["service_name"] == "Hàng nguyên chuyến"
    assert all("eta" not in record["payload"] for record in records)
    assert issues == []


async def test_logistics_lane_fixture_extracts_without_live_tracking_fields():
    artifact, _ = compile_template(LOGISTICS_SERVICE)
    service = TemplateIngestionService(None)  # type: ignore[arg-type]

    records, issues = service._extract_artifact(
        artifact,
        "Mã tuyến: SG-HN\nĐiểm đi: Hồ Chí Minh\nĐiểm đến: Hà Nội",
        file_id=None,
    )

    assert records[0]["record_type_key"] == "lane"
    assert records[0]["payload"] == {
        "lane_code": "SG-HN",
        "origin": "Hồ Chí Minh",
        "destination": "Hà Nội",
    }
    assert issues == []


async def test_shopping_product_pack_allows_product_without_unrelated_offer():
    artifact, _ = compile_template(SHOPPING_PRODUCT)
    service = TemplateIngestionService(None)  # type: ignore[arg-type]

    records, issues = service._extract_artifact(
        artifact,
        "SKU: SP-001\nTên sản phẩm: Áo khoác\nBảo hành: 12 tháng",
        file_id=None,
    )

    assert len(records) == 1
    assert records[0]["record_type_key"] == "product"
    assert records[0]["payload"]["sku"] == "SP-001"
    assert issues == []


async def test_preview_rejects_invalid_declared_field_types():
    definition = {
        "schema_version": "1",
        "record_types": [{
            "key": "offer",
            "display_name": "Offer",
            "natural_key_fields": ["code"],
            "fields": [
                {"key": "code", "type": "string", "required": True},
                {"key": "price", "type": "number", "required": True},
            ],
        }],
    }
    artifact, _ = compile_template(definition)
    service = TemplateIngestionService(None)  # type: ignore[arg-type]
    records, issues = service._extract_artifact(artifact, "code: A1\nprice: not-a-number", file_id=None)
    assert records == []
    assert any(issue["code"] == "invalid_field_type" for issue in issues)
    # A field that failed coercion must not also be reported as missing required.
    assert not any(issue["code"] == "missing_required_field" for issue in issues)


async def test_compiler_v2_preview_materializes_each_repeated_section_with_field_evidence():
    artifact, _ = compile_template(
        {
            "schema_version": "2",
            "record_types": [
                {
                    "key": "item",
                    "display_name": "Item",
                    "occurrence_mode": "repeated_section",
                    "max_records": 10,
                    "natural_key_fields": ["code"],
                    "fields": [
                        {"key": "code", "type": "string", "required": True},
                        {"key": "name", "type": "string", "required": True},
                    ],
                }
            ],
        }
    )
    service = TemplateIngestionService(None)  # type: ignore[arg-type]

    records, issues = service._extract_artifact(
        artifact,
        "code: A\nname: Alpha\n\ncode: B\nname: Beta",
        file_id=None,
    )

    assert issues == []
    assert [record["payload"] for record in records] == [
        {"code": "A", "name": "Alpha"},
        {"code": "B", "name": "Beta"},
    ]
    assert records[0]["evidence_sources"]["name"]["locator"].occurrence_id == "section:1"
