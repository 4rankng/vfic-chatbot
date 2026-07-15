import pytest

from app.services.ingestion.fact_repository import (
    MAX_FACT_QUERY_LIMIT,
    FactQueryError,
    validate_fact_query,
)
from app.services.knowledge.tools.domain_tools import get_job_locations


def test_active_fact_reader_joins_project_active_kb_version():
    # This is deliberately a source-level contract test: the repository is the
    # only generic-fact reader and must not expose draft/rejected KB releases.
    import inspect

    from app.services.ingestion.fact_repository import query_active_structured_facts

    source = inspect.getsource(query_active_structured_facts)
    assert "Project.active_kb_version_id == StructuredFact.kb_version_id" in source
    assert "StructuredFact.project_id == project_id" in source


def test_fact_query_rejects_unknown_record_types_fields_operators_and_unbounded_limits():
    artifact = {
        "record_types": [
            {"key": "product", "fields": [{"key": "sku"}, {"key": "name"}]}
        ]
    }

    assert validate_fact_query(
        artifact,
        record_type_key="product",
        filters=[{"field": "sku", "operator": "eq", "value": "SP-01"}],
        limit=1,
    ) == [{"field": "sku", "operator": "eq", "value": "SP-01"}]

    for record_type_key, filters, limit in [
        ("unknown", [], 1),
        ("product", [{"field": "price", "operator": "eq", "value": "1"}], 1),
        ("product", [{"field": "sku", "operator": "contains", "value": "SP"}], 1),
        ("product", [], MAX_FACT_QUERY_LIMIT + 1),
    ]:
        with pytest.raises(FactQueryError):
            validate_fact_query(
                artifact,
                record_type_key=record_type_key,
                filters=filters,
                limit=limit,
            )


def test_job_location_reader_uses_active_release_then_legacy_fallback():
    import inspect

    source = inspect.getsource(get_job_locations)
    assert "JobLocation.kb_version_id == active_kb_version_id" in source
    assert "JobLocation.kb_version_id.is_(None)" in source


def test_job_requirement_reader_does_not_drop_legacy_rows_without_active_release():
    # Source-level contract: with no active structured release, requirements must
    # read legacy unversioned rows (kb_version_id IS NULL) rather than compare
    # against NULL, which would silently match nothing and drop every row.
    import inspect

    from app.services.knowledge.tools.domain_tools import get_job_requirements

    source = inspect.getsource(get_job_requirements)
    assert "active_kb_version_id is not None" in source
    assert "JobRequirement.kb_version_id.is_(None)" in source
