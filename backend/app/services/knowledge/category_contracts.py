"""Deterministic validation helpers for project-owned RAG category documents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent, ScalarEvent

from app.schemas.knowledge_categories import (
    CATEGORY_DOCUMENT_MODELS,
    MAX_CATEGORY_RECORDS,
    CategoryDocument,
    KnowledgeCategoryKey,
)
from app.services.knowledge.text_ingestion import normalize_kb_value


_TEMPLATE_DIR = Path(__file__).with_name("templates") / "categories"
MAX_CATEGORY_YAML_BYTES = 500_000
MAX_CATEGORY_YAML_DEPTH = 32
MAX_CATEGORY_YAML_NODES = 20_000
MAX_CATEGORY_YAML_SCALAR_CHARS = 20_000


class _StrictSafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    seen: set[Any] = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key}",
                key_node.start_mark,
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    key: KnowledgeCategoryKey
    label_vi: str
    list_field: str
    template_filename: str


CATEGORY_DEFINITIONS: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(
        KnowledgeCategoryKey.JOBS,
        "Vị trí tuyển dụng",
        "jobs",
        "jobs.yaml",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.COMPENSATION,
        "Lương & thu nhập",
        "compensation",
        "compensation.yaml",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.REQUIREMENTS,
        "Yêu cầu ứng viên",
        "requirements",
        "requirements.yaml",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.WORK_SCHEDULES,
        "Ca làm việc",
        "work_schedules",
        "work_schedules.yaml",
    ),
    CategoryDefinition(KnowledgeCategoryKey.BENEFITS, "Phúc lợi", "benefits", "benefits.yaml"),
    CategoryDefinition(
        KnowledgeCategoryKey.ACCOMMODATION,
        "Chỗ ở",
        "accommodation",
        "accommodation.yaml",
    ),
    CategoryDefinition(KnowledgeCategoryKey.MEALS, "Bữa ăn", "meals", "meals.yaml"),
    CategoryDefinition(
        KnowledgeCategoryKey.TRANSPORTATION,
        "Đưa đón & lịch xe",
        "transportation",
        "transportation.yaml",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.INSURANCE,
        "Bảo hiểm",
        "insurance",
        "insurance.yaml",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.APPLICATION,
        "Ứng tuyển & nhận việc",
        "application",
        "application.yaml",
    ),
    CategoryDefinition(KnowledgeCategoryKey.CONTACTS, "Liên hệ", "contacts", "contacts.yaml"),
    CategoryDefinition(
        KnowledgeCategoryKey.FAQ,
        "Câu hỏi thường gặp",
        "faq",
        "faq.yaml",
    ),
)

_DEFINITIONS_BY_KEY = {definition.key: definition for definition in CATEGORY_DEFINITIONS}


class EmptyCategoryError(ValueError):
    """Raised when replacement content has no rows and clear was not requested."""


class UnknownJobReferenceError(ValueError):
    """Raised when a category references a job absent from the current Jobs category."""


class CategoryYamlError(ValueError):
    """Raised when source text is not one bounded YAML mapping document."""


def get_category_definition(key: KnowledgeCategoryKey | str) -> CategoryDefinition:
    return _DEFINITIONS_BY_KEY[KnowledgeCategoryKey(key)]


def load_category_template(key: KnowledgeCategoryKey | str) -> str:
    definition = get_category_definition(key)
    return (_TEMPLATE_DIR / definition.template_filename).read_text(encoding="utf-8")


def parse_category_yaml(
    key: KnowledgeCategoryKey | str,
    source_yaml: str,
    *,
    allow_empty: bool = False,
) -> CategoryDocument:
    if len(source_yaml.encode("utf-8")) > MAX_CATEGORY_YAML_BYTES:
        raise CategoryYamlError("category YAML exceeds the 500 KB limit")
    try:
        _validate_yaml_events(source_yaml)
        documents = list(yaml.load_all(source_yaml, Loader=_StrictSafeLoader))
    except CategoryYamlError:
        raise
    except yaml.YAMLError as exc:
        raise CategoryYamlError(f"invalid YAML: {exc}") from exc
    if len(documents) != 1:
        raise CategoryYamlError("category upload must contain exactly one YAML document")
    payload = documents[0]
    if not isinstance(payload, dict):
        raise CategoryYamlError("category YAML root must be a mapping")
    return validate_category_payload(key, payload, allow_empty=allow_empty)


def _validate_yaml_events(source_yaml: str) -> None:
    depth = 0
    nodes = 0
    for event in yaml.parse(source_yaml):
        if isinstance(event, AliasEvent):
            raise CategoryYamlError("YAML aliases are not supported")
        if isinstance(event, CollectionStartEvent):
            depth += 1
            nodes += 1
            if depth > MAX_CATEGORY_YAML_DEPTH:
                raise CategoryYamlError(
                    f"category YAML exceeds the depth limit of {MAX_CATEGORY_YAML_DEPTH}"
                )
        elif isinstance(event, CollectionEndEvent):
            depth -= 1
        elif isinstance(event, ScalarEvent):
            nodes += 1
            if len(event.value) > MAX_CATEGORY_YAML_SCALAR_CHARS:
                raise CategoryYamlError(
                    "category YAML scalar exceeds the "
                    f"{MAX_CATEGORY_YAML_SCALAR_CHARS:,} character limit"
                )
        if nodes > MAX_CATEGORY_YAML_NODES:
            raise CategoryYamlError(
                f"category YAML exceeds the {MAX_CATEGORY_YAML_NODES:,} node limit"
            )


def validate_category_payload(
    key: KnowledgeCategoryKey | str,
    payload: dict[str, Any],
    *,
    allow_empty: bool = False,
) -> CategoryDocument:
    category_key = KnowledgeCategoryKey(key)
    definition = get_category_definition(category_key)
    records = payload.get(definition.list_field)
    if isinstance(records, list) and len(records) > MAX_CATEGORY_RECORDS:
        raise CategoryYamlError(
            f"category exceeds the {MAX_CATEGORY_RECORDS:,} record limit"
        )
    normalized_payload = normalize_kb_value(payload)
    document = CATEGORY_DOCUMENT_MODELS[category_key].model_validate(normalized_payload)
    if not allow_empty and not getattr(document, definition.list_field):
        raise EmptyCategoryError(
            "category replacement must contain at least one row; use the explicit clear action"
        )
    return document


def validate_job_references(
    document: CategoryDocument,
    known_job_ids: set[str],
) -> None:
    definition = get_category_definition(document.category)
    if definition.key is KnowledgeCategoryKey.JOBS:
        return

    unknown: set[str] = set()
    for record in getattr(document, definition.list_field):
        unknown.update(set(getattr(record, "job_ids", [])) - known_job_ids)
    if unknown:
        raise UnknownJobReferenceError(
            f"unknown job reference(s) in this project: {', '.join(sorted(unknown))}"
        )


def canonical_category_json(document: CategoryDocument) -> str:
    payload = document.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def category_checksum(document: CategoryDocument) -> str:
    canonical = canonical_category_json(document).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
