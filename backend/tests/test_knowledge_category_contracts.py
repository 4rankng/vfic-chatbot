from copy import deepcopy

import pytest
import yaml
from pydantic import ValidationError

from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.models.knowledge import KnowledgeBaseMode
from app.schemas.projects import ProjectCreate
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
    CategoryYamlError,
    EmptyCategoryError,
    UnknownJobReferenceError,
    category_checksum,
    load_category_template,
    parse_category_yaml,
    validate_category_payload,
    validate_job_references,
)


def test_catalog_has_all_twelve_categories_in_product_order():
    assert [definition.key.value for definition in CATEGORY_DEFINITIONS] == [
        "jobs",
        "compensation",
        "requirements",
        "work_schedules",
        "benefits",
        "accommodation",
        "meals",
        "transportation",
        "insurance",
        "application",
        "contacts",
        "faq",
    ]


def test_project_creation_requires_exactly_one_mode_specific_setup():
    direct = ProjectCreate(
        slug="lg-display",
        name="LG Display",
        knowledge_mode=KnowledgeBaseMode.DIRECT_CONTEXT,
        discovery_card={"summary": "Nhà máy màn hình"},
    )
    rag = ProjectCreate(
        slug="samsung",
        name="Samsung",
        knowledge_mode=KnowledgeBaseMode.RAG,
    )

    assert direct.knowledge_mode is KnowledgeBaseMode.DIRECT_CONTEXT
    assert rag.discovery_card is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "slug": "lg-display",
            "name": "LG Display",
            "knowledge_mode": "DIRECT_CONTEXT",
        },
        {
            "slug": "lg-display",
            "name": "LG Display",
            "knowledge_mode": "RAG",
            "discovery_card": {"summary": "must be derived"},
        },
        {
            "slug": "lg-display",
            "name": "LG Display",
            "knowledge_mode": "RAG",
            "is_active": True,
        },
    ],
)
def test_project_creation_rejects_incomplete_or_mixed_mode_payload(payload):
    with pytest.raises(ValidationError):
        ProjectCreate.model_validate(payload)


@pytest.mark.parametrize("definition", CATEGORY_DEFINITIONS, ids=lambda value: value.key.value)
def test_code_owned_template_is_valid_empty_document(definition):
    payload = yaml.safe_load(load_category_template(definition.key))

    document = validate_category_payload(definition.key, payload, allow_empty=True)

    assert document.category == definition.key
    assert getattr(document, definition.list_field) == []
    assert "project" not in payload
    assert "factory" not in payload


def test_jobs_present_in_document_are_available_without_status_field():
    payload = {
        "schema_version": "1.0",
        "category": "jobs",
        "jobs": [
            {
                "id": "cong-nhan-san-xuat",
                "title": "Công nhân sản xuất",
                "location": "An Dương, Hải Phòng",
            }
        ],
    }

    document = validate_category_payload(KnowledgeCategoryKey.JOBS, payload)

    assert [job.id for job in document.jobs] == ["cong-nhan-san-xuat"]
    assert "status" not in type(document.jobs[0]).model_fields


def test_jobs_reject_manual_status_field():
    payload = {
        "category": "jobs",
        "jobs": [{"id": "job-1", "title": "Công nhân", "status": "active"}],
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_category_payload("jobs", payload)


def test_category_must_match_selected_upload_slot():
    payload = {"category": "benefits", "benefits": []}

    with pytest.raises(ValidationError):
        validate_category_payload("jobs", payload, allow_empty=True)


def test_unknown_top_level_field_is_rejected():
    payload = {"category": "jobs", "jobs": [], "factory": "LG"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_category_payload("jobs", payload, allow_empty=True)


def test_duplicate_stable_ids_are_rejected():
    payload = {
        "category": "contacts",
        "contacts": [
            {"id": "recruiter", "name": "Tư vấn 1"},
            {"id": "recruiter", "name": "Tư vấn 2"},
        ],
    }

    with pytest.raises(ValidationError, match="duplicate stable id"):
        validate_category_payload("contacts", payload)


def test_empty_replacement_requires_explicit_clear_action():
    payload = {"category": "jobs", "jobs": []}

    with pytest.raises(EmptyCategoryError, match="explicit clear action"):
        validate_category_payload("jobs", payload)


def test_job_reference_must_exist_in_same_projects_jobs_category():
    payload = {
        "category": "requirements",
        "requirements": [{"id": "req-1", "job_ids": ["missing-job"]}],
    }
    document = validate_category_payload("requirements", payload)

    with pytest.raises(UnknownJobReferenceError, match="missing-job"):
        validate_job_references(document, {"job-1"})


def test_empty_job_references_mean_category_applies_project_wide():
    payload = {
        "category": "benefits",
        "benefits": [{"id": "benefit-1", "job_ids": [], "name": "Khám sức khỏe"}],
    }
    document = validate_category_payload("benefits", payload)

    validate_job_references(document, set())


def test_checksum_is_deterministic_for_equivalent_key_order():
    payload = {
        "category": "jobs",
        "jobs": [{"id": "job-1", "title": "Công nhân", "keywords": ["điện tử"]}],
    }
    reordered = deepcopy(payload)
    reordered["jobs"][0] = {
        "keywords": ["điện tử"],
        "title": "Công nhân",
        "id": "job-1",
    }

    first = validate_category_payload("jobs", payload)
    second = validate_category_payload("jobs", reordered)

    assert category_checksum(first) == category_checksum(second)


def test_yaml_parser_accepts_one_mapping_document():
    document = parse_category_yaml(
        "jobs",
        "category: jobs\njobs:\n  - id: job-1\n    title: Công nhân\n",
    )

    assert document.jobs[0].id == "job-1"


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("- category\n- jobs\n", "root must be a mapping"),
        (
            "category: jobs\njobs: []\n---\ncategory: jobs\njobs: []\n",
            "exactly one YAML document",
        ),
    ],
)
def test_yaml_parser_rejects_ambiguous_document_shapes(source, message):
    with pytest.raises(CategoryYamlError, match=message):
        parse_category_yaml("jobs", source, allow_empty=True)


def test_yaml_parser_rejects_oversized_source_before_parsing():
    with pytest.raises(CategoryYamlError, match="500 KB"):
        parse_category_yaml("jobs", "x" * 500_001)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "category: jobs\ncategory: jobs\njobs:\n  - id: one\n    title: One\n",
            "duplicate key",
        ),
        (
            "category: jobs\ndefaults: &defaults {title: One}\njobs:\n  - id: one\n    <<: *defaults\n",
            "aliases are not supported",
        ),
    ],
)
def test_yaml_parser_rejects_duplicate_keys_and_alias_expansion(source, message):
    with pytest.raises(CategoryYamlError, match=message):
        parse_category_yaml("jobs", source)
