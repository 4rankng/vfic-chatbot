"""Retired knowledge references disappear without rewriting historical facts."""

from copy import deepcopy
import json

import pytest

from app.project_knowledge.domain.legacy_job_references import (
    strip_legacy_job_reference_fields,
    strip_legacy_job_reference_source,
)
from app.services.knowledge.category_contracts import validate_category_payload
from app.services.knowledge.category_markdown import (
    MAX_CATEGORY_MARKDOWN_BYTES,
    MAX_CATEGORY_MARKDOWN_LINES,
    CategoryMarkdownError,
    build_source_markdown,
    parse_category_markdown,
)


def _payload():
    return {
        "schema_version": "1.0",
        "category": "benefits",
        "benefits": [
            {
                "id": "free-food",
                "name": "Cơm ca miễn phí",
                "description": 'Ghi chú giữ nguyên từ "job_ids" và "jobs_ids" trong câu.',
                "job_ids": ["old-operator"],
                "jobs_ids": ["old-inspector"],
                "vacancies": None,
                "employment_type": "temporary",
            }
        ],
    }


def _markdown(fields: str) -> str:
    return (
        '---\nschema_version: "1.0"\ncategory: benefits\n---\n'
        "\n## benefits\n\n### record: free-food\n"
        'name: "Cơm ca miễn phí"\n'
        f"{fields}"
        'description: "Áp dụng cho công nhân, ghi chú job_ids được giữ nguyên."\n'
    )


def test_payload_cleanup_is_recursive_non_mutating_and_keeps_plain_text():
    payload = _payload()
    original = deepcopy(payload)
    clean = strip_legacy_job_reference_fields(payload)

    assert payload == original
    assert clean == {
        "schema_version": "1.0",
        "category": "benefits",
        "benefits": [
            {
                "id": "free-food",
                "name": "Cơm ca miễn phí",
                "description": original["benefits"][0]["description"],
            }
        ],
    }
    assert strip_legacy_job_reference_fields(clean) == clean


def test_retired_mapping_keys_do_not_remove_unrelated_ids_or_checkpoints():
    value = {
        "checksum": "legacy-hash",
        "prepared_document_id": "original-preparation",
        "record_count": 2,
        "job_ids": ["old"],
        "published_snapshot": {"jobs": {"active": "revision", "latest": 7}},
        "entities": {"stable_id": "worker", "jobs_ids": ["old"]},
        "vacancies": None,
        "employment_type": "permanent",
        "id": "record",
    }
    cleaned = strip_legacy_job_reference_fields(value)
    assert cleaned["checksum"] == value["checksum"]
    assert cleaned["prepared_document_id"] == value["prepared_document_id"]
    assert cleaned["record_count"] == value["record_count"]
    assert cleaned["published_snapshot"] == value["published_snapshot"]
    assert cleaned["entities"] == {"stable_id": "worker"}
    assert cleaned["id"] == "record"
    assert "vacancies" not in cleaned
    assert "employment_type" not in cleaned


def test_old_saved_payload_validates_against_current_strict_schema():
    document = validate_category_payload("benefits", _payload())
    record = document.model_dump(mode="json")["benefits"][0]
    assert "job_ids" not in record
    assert "jobs_ids" not in record
    assert record["description"] == _payload()["benefits"][0]["description"]


@pytest.mark.parametrize("field", ["job_ids", "jobs_ids"])
@pytest.mark.parametrize(
    "value",
    [
        "[]",
        '["old-operator"]',
        "[old-operator]",
        '[\n"old-operator",\n"old-inspector"\n]',
        '["old-operator",\n"old-inspector"]',
    ],
)
def test_old_markdown_inline_list_fields_parse_as_project_knowledge(field, value):
    source = _markdown(f"{field}: {value}\n")
    document = parse_category_markdown("benefits", source)
    assert document.benefits[0].name == "Cơm ca miễn phí"
    assert document.benefits[0].description.endswith("job_ids được giữ nguyên.")
    assert field not in document.model_dump(mode="json")["benefits"][0]


@pytest.mark.parametrize("field", ["job_ids", "jobs_ids"])
def test_old_markdown_dash_list_fields_keep_the_following_facts(field):
    source = _markdown(f'{field}:\n- "old-operator"\n- "old-inspector"\n')
    cleaned = strip_legacy_job_reference_source(source)
    assert "old-operator" not in cleaned
    assert "old-inspector" not in cleaned
    assert 'name: "Cơm ca miễn phí"' in cleaned
    assert 'description: "Áp dụng cho công nhân' in cleaned
    assert parse_category_markdown("benefits", source).benefits[0].name == "Cơm ca miễn phí"


def test_source_cleanup_preserves_quoted_prose_fences_comments_and_block_scalars():
    source = (
        "Câu văn giải thích job_ids và jobs_ids được giữ nguyên.\n"
        'description: "job_ids: [old] là ví dụ trong một câu."\n'
        "job_ids: mô tả thông thường, không phải trường danh sách.\n"
        "> jobs_ids: [quoted-example]\n"
        "```markdown\njob_ids: [code-example]\n```\n"
        '~~~json\n{"jobs_ids": ["code-example"]}\n~~~\n'
        "<!--\njob_ids: [comment-example]\n-->\n"
        "notes: |\n  job_ids: [prose-example]\n  Giữ nguyên nội dung ghi chú.\n"
        'description: "employment_type: null chỉ là một ví dụ trong câu."\n'
        "> vacancies: null\n"
        "```yaml\nvacancies: null\nemployment_type: temporary\n```\n"
        "<!--\nvacancies: null\n-->\n"
        "notes: |\n  employment_type: temporary\n  vacancies: 100\n"
        "salary: 6000000\n"
    )
    assert strip_legacy_job_reference_source(source) == source


@pytest.mark.parametrize(
    "key", ["notes", '"notes"', "'ghi chú'", '"notes \\"for admin\\""', "'worker''s notes'"]
)
@pytest.mark.parametrize("indicator", ["|", ">-", "|2", "|2-", "|-2", "| # ghi chú"])
@pytest.mark.parametrize("bullet", ["", "- "])
def test_role_metadata_examples_in_valid_note_block_scalars_survive(key, indicator, bullet):
    content_indent = " " * (len(bullet) + 2)
    sibling_indent = " " * len(bullet)
    note = (
        f"{bullet}{key}: {indicator}\n"
        f"{content_indent}employment_type: temporary\n"
        f"{content_indent}vacancies: 100\n"
        f"{content_indent}Văn bản giải thích hợp đồng.\n"
    )
    source = note + f"{sibling_indent}employment_type: null\n{sibling_indent}salary: 6000000\n"

    assert strip_legacy_job_reference_source(source) == note + f"{sibling_indent}salary: 6000000\n"


def test_category_chunk_cleanup_strips_only_the_retired_field_lines():
    source = (
        'Phúc lợi\r\nid: "food"\r\njob_ids: ["old-operator"]\r\n'
        'jobs_ids: []\r\nvacancies: null\r\nemployment_type: null\r\nname: "Cơm ca miễn phí"\r\n'
        'description: "Người lao động không cần biết job_ids."\r\n'
    )
    cleaned = strip_legacy_job_reference_source(source)
    assert cleaned == (
        'Phúc lợi\r\nid: "food"\r\nname: "Cơm ca miễn phí"\r\n'
        'description: "Người lao động không cần biết job_ids."\r\n'
    )
    assert strip_legacy_job_reference_source(cleaned) == cleaned


@pytest.mark.parametrize(
    "fields",
    [
        "vacancies: null\nemployment_type: null\n",
        "vacancies: 100\nemployment_type: temporary\n",
        'vacancies: 0\nemployment_type: "Thời vụ"\n',
        '- vacancies: null\n- employment_type: "permanent"\n',
        '"vacancies": null\n\'employment_type\': "contract"\n',
        "vacancies:\n  - 100\nemployment_type:\n  - temporary\n",
        "employment_type: |\n  Thời vụ\n  Hợp đồng ba tháng\nvacancies: >-\n  100\n",
        "- employment_type: |2-\n    Thời vụ\n  vacancies: null\n",
    ],
)
def test_old_role_metadata_is_removed_from_unwrapped_markdown_evidence(fields):
    source = "Vị trí tuyển dụng\n" + fields + "title: Lắp ráp\nLương: 6 triệu\n"
    expected = "Vị trí tuyển dụng\ntitle: Lắp ráp\nLương: 6 triệu\n"

    assert strip_legacy_job_reference_source(source) == expected
    assert strip_legacy_job_reference_source(expected) == expected


def test_cached_bullet_wrapped_field_does_not_remove_later_factual_bullets():
    source = '- job_ids:\n  - "old-role"\n- Cơm ca miễn phí.\n  Nguồn: Dự án A\n'
    assert strip_legacy_job_reference_source(source) == "- Cơm ca miễn phí.\n  Nguồn: Dự án A\n"
    assert (
        strip_legacy_job_reference_source('- jobs_ids: ["old-role"]\n  Nguồn: Dự án A\n')
        == "  Nguồn: Dự án A\n"
    )


def test_json_record_dump_cleanup_keeps_other_fields_and_nested_facts():
    original = _payload()
    source = json.dumps(original, ensure_ascii=False, indent=2) + "\n"
    cleaned = strip_legacy_job_reference_source(source)
    assert json.loads(cleaned) == strip_legacy_job_reference_fields(original)
    assert cleaned.endswith("\n")
    embedded = "Phúc lợi\n" + json.dumps(original["benefits"][0], ensure_ascii=False) + "\n"
    embedded_cleaned = strip_legacy_job_reference_source(embedded)
    assert json.loads(embedded_cleaned.splitlines()[1]) == strip_legacy_job_reference_fields(
        original["benefits"][0]
    )


@pytest.mark.parametrize("prefix", ["", "- ", "  * "])
@pytest.mark.parametrize("multiline", [False, True])
def test_cached_json_evidence_after_heading_or_bullet_is_cleaned(prefix, multiline):
    record = {
        "job_ids": ["old-role"],
        "jobs_ids": ["old-role-2"],
        "vacancies": None,
        "employment_type": "temporary",
        "answer": "Cơm ca miễn phí",
        "notes": "Từ job_ids nằm trong câu.",
    }
    encoded = json.dumps(record, ensure_ascii=False, indent=2 if multiline else None)
    source = "Phúc lợi\n" + prefix + encoded + "\n  Nguồn: Bảng thông tin (Dự án A)\n"
    cleaned = strip_legacy_job_reference_source(source)
    assert '"job_ids":' not in cleaned
    assert '"jobs_ids":' not in cleaned
    assert '"vacancies":' not in cleaned
    assert '"employment_type":' not in cleaned
    assert "Cơm ca miễn phí" in cleaned
    assert "Từ job_ids nằm trong câu." in cleaned
    assert cleaned.endswith("\n  Nguồn: Bảng thông tin (Dự án A)\n")
    assert cleaned.startswith("Phúc lợi\n" + prefix)
    assert strip_legacy_job_reference_source(cleaned) == cleaned


def test_malformed_array_cannot_consume_a_later_heading_or_fenced_example():
    source = (
        "job_ids: [\n## Kiến thức khác\nLương 6.000.000 đồng.\n"
        "```markdown\njobs_ids: [example]\n```\n"
    )
    assert strip_legacy_job_reference_source(source) == source


def test_malformed_json_with_many_open_brackets_keeps_prose_without_repeated_scans():
    source = "Phúc lợi\n" + "[\n" * 5_000 + "Thông tin lương vẫn giữ nguyên.\n"
    assert strip_legacy_job_reference_source(source) == source


@pytest.mark.parametrize(
    "source",
    [
        '{"job_ids": ["old"]}',
        '[{"jobs_ids": ["old"]}]',
        '{"nested": [{"job_ids": ["old"]}]}',
        '- {"job_ids": ["old"]}\n',
        '- {\n  "jobs_ids": ["old"]\n}\n',
        '{"vacancies": null, "employment_type": null}',
        '[{"vacancies": 100, "employment_type": "temporary"}]',
        '- {"vacancies": null}\n',
    ],
)
def test_reference_only_json_does_not_become_a_fake_nonempty_knowledge_source(source):
    assert not strip_legacy_job_reference_source(source).strip()


def test_emptied_json_evidence_keeps_the_following_citation_and_prose():
    source = '- {"job_ids": ["old"]}\n  Nguồn: Dự án A\nLương 6.000.000 đồng.\n'
    assert (
        strip_legacy_job_reference_source(source) == "\n  Nguồn: Dự án A\nLương 6.000.000 đồng.\n"
    )


@pytest.mark.parametrize("source", ["{}", "[]", "[{}]", '{"nested": []}'])
def test_already_empty_original_json_is_not_changed(source):
    assert strip_legacy_job_reference_source(source) == source


@pytest.mark.parametrize("value", [0, False, None, "", "Cơm ca miễn phí"])
def test_real_scalar_values_survive_reference_removal(value):
    source = json.dumps({"job_ids": ["old"], "value": value}, ensure_ascii=False)
    cleaned = strip_legacy_job_reference_source(source)
    assert json.loads(cleaned) == {"value": value}


def test_renderer_does_not_emit_fields_from_old_payload_or_mutate_it():
    payload = _payload()
    original = deepcopy(payload)
    source = build_source_markdown(payload)
    assert "\njob_ids:" not in source
    assert "\njobs_ids:" not in source
    assert payload == original
    assert parse_category_markdown("benefits", source).model_dump(mode="json") == (
        validate_category_payload("benefits", payload).model_dump(mode="json")
    )


def test_original_byte_limit_is_enforced_before_legacy_cleanup():
    source = _markdown('job_ids: ["' + "x" * MAX_CATEGORY_MARKDOWN_BYTES + '"]\n')
    with pytest.raises(CategoryMarkdownError, match="500 KB"):
        parse_category_markdown("benefits", source)


def test_original_line_limit_is_enforced_before_legacy_cleanup():
    source = _markdown("job_ids:\n" + '- "old"\n' * MAX_CATEGORY_MARKDOWN_LINES)
    with pytest.raises(CategoryMarkdownError, match="line limit"):
        parse_category_markdown("benefits", source)
