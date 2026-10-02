from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.knowledge_categories import JobItem, KnowledgeCategoryKey
from app.models.knowledge import KnowledgeBaseMode
from app.schemas.projects import ProjectCreate
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
    EmptyCategoryError,
    category_checksum,
    build_project_knowledge_template,
    load_category_template,
    validate_category_payload,
)
from app.services.knowledge.category_markdown import (
    CategoryMarkdownError,
    parse_category_markdown,
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


def _jobs_doc(*records: str) -> str:
    """One jobs Category Markdown v1 document wrapping the given record blocks."""
    return (
        "---\n"
        'schema_version: "1.0"\n'
        "category: jobs\n"
        "---\n"
        "\n"
        "## jobs\n"
        "\n" + "".join(records)
    )


@pytest.mark.parametrize("definition", CATEGORY_DEFINITIONS, ids=lambda value: value.key.value)
def test_code_owned_template_is_valid_empty_document(definition):
    assert definition.template_filename.endswith(".md")

    document = parse_category_markdown(
        definition.key, load_category_template(definition.key), allow_empty=True
    )
    payload = document.model_dump(mode="json")

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


@pytest.mark.parametrize("definition", CATEGORY_DEFINITIONS, ids=lambda value: value.key.value)
def test_category_must_match_selected_upload_slot(definition):
    other_category = next(item.key for item in CATEGORY_DEFINITIONS if item.key != definition.key)
    payload = {"category": other_category.value, definition.list_field: []}

    with pytest.raises(ValidationError, match="Input should be"):
        validate_category_payload(definition.key, payload, allow_empty=True)


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


def test_category_records_have_no_job_associations():
    from app.schemas.knowledge_categories import CATEGORY_DOCUMENT_MODELS

    for definition in CATEGORY_DEFINITIONS:
        document_model = CATEGORY_DOCUMENT_MODELS[definition.key]
        list_annotation = document_model.model_fields[definition.list_field].annotation
        record_model = list_annotation.__args__[0]
        assert "job_ids" not in record_model.model_fields
        assert "jobs_ids" not in record_model.model_fields


def test_project_wide_category_does_not_require_a_jobs_document():
    document = validate_category_payload("benefits", {
        "category": "benefits",
        "benefits": [{"id": "benefit-1", "name": "Khám sức khỏe"}],
    })
    assert document.benefits[0].name == "Khám sức khỏe"


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


def test_checksum_is_deterministic_for_unicode_and_line_ending_equivalence():
    document_lines = [
        "---",
        'schema_version: "1.0"',
        "category: contacts",
        "---",
        "",
        "## contacts",
        "",
        "### record: recruiter",
        'name: "Tư vấn"',
    ]
    first = parse_category_markdown("contacts", "\r\n".join(document_lines) + "\r\n")
    second = parse_category_markdown("contacts", "\n".join(document_lines) + "\n")

    assert first.contacts[0].name == "Tư vấn"
    assert category_checksum(first) == category_checksum(second)


def test_markdown_parser_accepts_one_record_document():
    document = parse_category_markdown(
        "jobs", _jobs_doc('### record: job-1\ntitle: "Công nhân"\n')
    )

    assert document.jobs[0].id == "job-1"


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            '## jobs\n\n### record: a\ntitle: "X"\n\n## jobs\n',
            "duplicate section heading",
        ),
        (
            "---\n"
            'schema_version: "1.0"\n'
            "category: jobs\n"
            "---\n"
            "\n"
            "## jobs\n"
            "\n"
            "## jobs\n",
            "duplicate section heading",
        ),
    ],
)
def test_markdown_parser_rejects_ambiguous_document_shapes(source, message):
    with pytest.raises(CategoryMarkdownError, match=message):
        parse_category_markdown("jobs", source, allow_empty=True)


def test_markdown_parser_rejects_oversized_source_before_parsing():
    with pytest.raises(CategoryMarkdownError, match="500 KB"):
        parse_category_markdown("jobs", "x" * 500_001)


def test_markdown_parser_rejects_excessive_lines_before_parsing():
    source = "\n".join(["- tràn dòng"] * 20_001)

    with pytest.raises(CategoryMarkdownError, match="20,000 line limit"):
        parse_category_markdown("jobs", source)


def test_markdown_parser_rejects_excessive_scalar_before_construction():
    source = _jobs_doc('### record: one\ntitle: "' + "x" * 20_001 + '"\n')

    with pytest.raises(CategoryMarkdownError, match="scalar exceeds"):
        parse_category_markdown("jobs", source)


def test_category_rejects_more_than_one_thousand_records():
    records = "".join(
        f'### record: job-{index}\ntitle: "Job {index}"\n' for index in range(1_001)
    )

    with pytest.raises(CategoryMarkdownError, match="1,000 record limit"):
        parse_category_markdown("jobs", _jobs_doc(records))


@pytest.mark.parametrize(
    ("record_block", "message"),
    [
        ('### record: a\ntitle: "X"\ntitle: "Y"\n', "duplicate field 'title'"),
        ('### record: a\ntitle: "X"\n### record: a\ntitle: "Y"\n', "duplicate record id 'a'"),
    ],
)
def test_markdown_parser_rejects_duplicate_fields_and_record_ids(record_block, message):
    with pytest.raises(CategoryMarkdownError, match=message):
        parse_category_markdown("jobs", _jobs_doc(record_block))



def test_jobs_authoring_contract_and_templates_omit_retired_metadata():
    for field in ("vacancies", "employment_type"):
        assert field not in JobItem.model_fields
        assert field not in JobItem.model_json_schema()["properties"]
        assert field not in load_category_template("jobs")
        assert field not in build_project_knowledge_template()


@pytest.mark.parametrize(
    ("vacancies", "employment_type"), [(None, None), (100, "temporary")],
)
def test_old_job_metadata_is_accepted_but_not_retained_in_category_payload(vacancies, employment_type):
    payload = {
        "category": "jobs",
        "jobs": [{"id": "assembly", "title": "Lắp ráp", "vacancies": vacancies, "employment_type": employment_type}],
    }
    document = validate_category_payload("jobs", payload)
    record = document.jobs[0].model_dump(mode="json")
    assert record["title"] == "Lắp ráp"
    assert "vacancies" not in record
    assert "employment_type" not in record
    # Boundary compatibility does not mutate retained historical payloads.
    assert payload["jobs"][0]["vacancies"] == vacancies
    assert payload["jobs"][0]["employment_type"] == employment_type


@pytest.mark.parametrize(
    "old_fields", ["vacancies: null\nemployment_type: null\n", "vacancies: 100\nemployment_type: temporary\n"],
)
def test_old_job_markdown_roundtrips_without_retired_metadata(old_fields):
    from app.services.knowledge.category_markdown import build_source_markdown

    document = parse_category_markdown("jobs", _jobs_doc(
        '### record: assembly\ntitle: "Lắp ráp"\n' + old_fields
    ))
    source = build_source_markdown(document.model_dump(mode="json"))
    assert "vacancies" not in source
    assert "employment_type" not in source
    assert parse_category_markdown("jobs", source).jobs[0].title == "Lắp ráp"
