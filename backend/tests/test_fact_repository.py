"""Fact-query validation is a pure function; the DB readers are integration tests.

``query_active_structured_facts``, ``get_job_locations`` and
``get_job_requirements`` are asserted behaviourally against the disposable DB in
``tests/integration/test_fact_repository_active_release.py`` — reading their
source text proved nothing about which rows they return.
"""

import pytest

from app.services.ingestion.fact_repository import (
    MAX_FACT_QUERY_LIMIT,
    FactQueryError,
    validate_fact_query,
)


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
