"""Strict contracts for immutable case workflow authoring."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AttributeFieldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "number", "boolean", "date", "datetime"]
    label: str = Field(min_length=1, max_length=80)
    required: bool = False
    max_length: int | None = Field(default=None, ge=1, le=2000)
    enum: list[str | int | float | bool] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_type_options(self) -> "AttributeFieldDefinition":
        if self.max_length is not None and self.type != "string":
            raise ValueError("max_length is valid only for string fields")
        if self.enum is not None:
            if len({(type(item).__name__, str(item)) for item in self.enum}) != len(self.enum):
                raise ValueError("enum values must be unique")
            expected = {"string": str, "integer": int, "number": (int, float), "boolean": bool}.get(
                self.type
            )
            if expected is None or any(
                not isinstance(item, expected)
                or (self.type != "boolean" and isinstance(item, bool))
                for item in self.enum
            ):
                raise ValueError("enum values must match the field type")
        return self


class WorkflowStageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    label: str = Field(min_length=1, max_length=160)
    position: int = Field(ge=0, le=32767)
    is_initial: bool = False
    is_terminal: bool = False


class WorkflowTransitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_stage_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    to_stage_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")


class WorkflowTagInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,47}$")
    label: str = Field(min_length=1, max_length=80)
    tone: Literal["neutral", "info", "success", "warning", "danger"]
    position: int = Field(ge=0, le=32767)


class CaseWorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    workflow_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    label: str = Field(min_length=1, max_length=160)
    expected_previous_version_no: int | None = Field(default=None, ge=1)
    stages: list[WorkflowStageInput] = Field(min_length=1, max_length=64)
    transitions: list[WorkflowTransitionInput] = Field(default_factory=list, max_length=256)
    tags: list[WorkflowTagInput] = Field(default_factory=list, max_length=64)
    case_attribute_schema: dict[str, AttributeFieldDefinition] = Field(
        default_factory=dict, max_length=32
    )

    @field_validator("case_attribute_schema")
    @classmethod
    def validate_attribute_keys(
        cls, value: dict[str, AttributeFieldDefinition]
    ) -> dict[str, AttributeFieldDefinition]:
        blocked = {
            "assignment",
            "assigned_user_id",
            "stage",
            "stage_key",
            "status",
            "lifecycle",
            "price",
            "stock",
            "vacancy",
            "order",
            "shipment",
            "payment",
            "eta",
        }
        invalid = [
            key
            for key in value
            if not key
            or len(key) > 64
            or key.lower() in blocked
            or not key.replace("_", "a").replace("-", "a").isalnum()
        ]
        if invalid:
            raise ValueError(f"invalid or operational-authority attribute keys: {sorted(invalid)}")
        return value


class CaseWorkflowSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    pack_key: str
    workflow_key: str
    version_no: int
    label: str
    checksum: str
    created_by: uuid.UUID | None
    created_at: datetime


class WorkflowStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    label: str
    position: int
    is_initial: bool
    is_terminal: bool


class WorkflowTransitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_stage_key: str
    to_stage_key: str


class WorkflowTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    label: str
    tone: str
    position: int


class CaseWorkflowOut(CaseWorkflowSummaryOut):
    schema_version: int
    case_attribute_schema: dict[str, AttributeFieldDefinition]
    stages: list[WorkflowStageOut]
    transitions: list[WorkflowTransitionOut]
    tags: list[WorkflowTagOut]


class CaseWorkflowListResponse(BaseModel):
    data: list[CaseWorkflowSummaryOut]
    total: int
