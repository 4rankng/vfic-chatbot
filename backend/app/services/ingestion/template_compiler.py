"""Closed, deterministic compiler for admin-authored ingestion templates.

Templates describe data, never behaviour: the compiler rejects executable
constructs and returns a canonical artifact that workers can replay unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

COMPILER_VERSION = "1"
MAX_RECORD_TYPES = 24
MAX_FIELDS_PER_RECORD = 48
MAX_ALIASES_PER_FIELD = 12
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FORBIDDEN = {"prompt", "tool", "resolver", "sql", "regex", "script", "url", "expression"}


class TemplateCompileError(ValueError):
    def __init__(self, issues: list[dict]) -> None:
        self.issues = issues
        super().__init__("Template definition is invalid.")


class FieldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    type: Literal["string", "number", "integer", "boolean", "date", "time", "enum"]
    aliases: list[str] = Field(default_factory=list)
    required: bool = False
    enum_values: list[str] = Field(default_factory=list)
    source_mode: Literal["sourced_fact", "derived", "narrative"] = "sourced_fact"
    constant: str | int | float | bool | None = None

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _KEY.fullmatch(value) or value in _FORBIDDEN:
            raise ValueError("must be a safe stable key")
        return value

    @field_validator("aliases")
    @classmethod
    def bounded_aliases(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_ALIASES_PER_FIELD or any(not item.strip() for item in value):
            raise ValueError("aliases must be non-empty and bounded")
        return value

    @field_validator("enum_values")
    @classmethod
    def enum_only_for_enum(cls, value: list[str], info) -> list[str]:
        if len(value) > 64:
            raise ValueError("too many enum values")
        if info.data.get("type") == "enum" and not value:
            raise ValueError("enum fields require enum_values")
        return value


class RecordDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    display_name: str
    fields: list[FieldDefinition]
    natural_key_fields: list[str]
    scope_type: Literal["global", "company", "location", "job_posting", "campaign"] = "global"
    scope_id_field: str | None = None

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _KEY.fullmatch(value) or value in _FORBIDDEN:
            raise ValueError("must be a safe stable key")
        return value

    @field_validator("fields")
    @classmethod
    def valid_fields(cls, value: list[FieldDefinition]) -> list[FieldDefinition]:
        keys = [field.key for field in value]
        if not value or len(value) > MAX_FIELDS_PER_RECORD or len(keys) != len(set(keys)):
            raise ValueError("fields must be non-empty, unique, and bounded")
        return value

    @field_validator("natural_key_fields")
    @classmethod
    def valid_natural_key(cls, value: list[str], info) -> list[str]:
        field_keys = {field.key for field in info.data.get("fields", [])}
        if not value or len(value) > 8 or not set(value).issubset(field_keys):
            raise ValueError("natural_key_fields must refer to declared fields")
        return value

    @model_validator(mode="after")
    def valid_scope_id(self) -> "RecordDefinition":
        field_keys = {field.key for field in self.fields}
        if self.scope_type != "global" and (
            self.scope_id_field is None or self.scope_id_field not in field_keys
        ):
            raise ValueError("non-global scopes require a declared scope_id_field")
        if self.scope_id_field is not None and self.scope_id_field not in field_keys:
            raise ValueError("scope_id_field must refer to a declared field")
        return self


class TemplateDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = "1"
    record_types: list[RecordDefinition]

    @field_validator("record_types")
    @classmethod
    def valid_records(cls, value: list[RecordDefinition]) -> list[RecordDefinition]:
        keys = [record.key for record in value]
        if not value or len(value) > MAX_RECORD_TYPES or len(keys) != len(set(keys)):
            raise ValueError("record types must be non-empty, unique, and bounded")
        return value


def compile_template(definition: dict) -> tuple[dict, str]:
    """Return a canonical stored IR and its SHA-256 checksum."""
    try:
        parsed = TemplateDefinition.model_validate(definition)
    except ValidationError as exc:
        raise TemplateCompileError(exc.errors(include_url=False)) from exc
    artifact = {
        "compiler_version": COMPILER_VERSION,
        "schema_version": parsed.schema_version,
        "record_types": [record.model_dump(mode="json") for record in parsed.record_types],
    }
    canonical = json.dumps(artifact, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return artifact, hashlib.sha256(canonical.encode()).hexdigest()
