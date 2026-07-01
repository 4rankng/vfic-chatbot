"""Persona schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import PROACTIVE_48H_WINDOW_SECONDS, PROACTIVE_FOLLOWUP_CAP
from app.models.lead import LeadScore, LeadStage


MAX_FOLLOWUP_CADENCE_HOURS = PROACTIVE_48H_WINDOW_SECONDS // 3600


class PersonaFollowupRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    cadence_hours: list[int] = Field(default_factory=list)
    eligible_stages: list[LeadStage] = Field(default_factory=lambda: [LeadStage.NEW])

    @field_validator("cadence_hours")
    @classmethod
    def validate_cadence_hours(cls, value: list[int]) -> list[int]:
        if len(value) > PROACTIVE_FOLLOWUP_CAP:
            raise ValueError(f"cadence may contain at most {PROACTIVE_FOLLOWUP_CAP} entries")
        if any(v <= 0 for v in value):
            raise ValueError("cadence hours must be positive")
        if value != sorted(value):
            raise ValueError("cadence hours must be sorted ascending")
        if any(v > MAX_FOLLOWUP_CADENCE_HOURS for v in value):
            raise ValueError(
                f"cadence hours must be within the {MAX_FOLLOWUP_CADENCE_HOURS}h proactive window"
            )
        return value

    @field_validator("eligible_stages")
    @classmethod
    def validate_eligible_stages(cls, value: list[LeadStage]) -> list[LeadStage]:
        if not value:
            raise ValueError("at least one eligible stage is required")
        deduped: list[LeadStage] = []
        for stage in value:
            if stage not in deduped:
                deduped.append(stage)
        return deduped

    @model_validator(mode="after")
    def validate_enabled_rule_has_cadence(self) -> "PersonaFollowupRule":
        if self.enabled and not self.cadence_hours:
            raise ValueError("enabled follow-up rules require at least one cadence value")
        return self


class PersonaFollowupRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hot: PersonaFollowupRule = Field(
        default_factory=lambda: PersonaFollowupRule(cadence_hours=[10, 22, 46])
    )
    warm: PersonaFollowupRule = Field(
        default_factory=lambda: PersonaFollowupRule(cadence_hours=[22, 46])
    )
    not_interested: PersonaFollowupRule = Field(
        default_factory=lambda: PersonaFollowupRule(cadence_hours=[46])
    )

    def rule_for_score(self, score: LeadScore | str | None) -> PersonaFollowupRule | None:
        if score is None:
            return None
        key = score.value if isinstance(score, LeadScore) else str(score)
        return getattr(self, key, None)


def default_followup_rules() -> PersonaFollowupRules:
    return PersonaFollowupRules()


def default_followup_rules_dict() -> dict[str, Any]:
    return default_followup_rules().model_dump(mode="json")


def normalize_followup_rules(value: Any) -> PersonaFollowupRules:
    if isinstance(value, PersonaFollowupRules):
        return value
    if value is None:
        return default_followup_rules()
    return PersonaFollowupRules.model_validate(value)


def _slugify(name: str) -> str:
    out = []
    for ch in name.strip().lower():
        out.append(ch if ch.isalnum() or ch in "-_" else "-")
    slug = "".join(out).strip("-")
    # collapse repeated separators
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "persona"


class PersonaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID | None = None
    name: str
    slug: str
    body_md: str
    followup_rules: PersonaFollowupRules = Field(default_factory=default_followup_rules)
    is_active: bool
    notes: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    assigned_projects: list[ProjectMini] = []


class PersonaListResponse(BaseModel):
    data: list[PersonaOut]
    total: int


class PersonaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    body_md: str = Field(min_length=1)
    slug: str | None = None  # derived from name if absent
    notes: str | None = None
    is_active: bool = False
    followup_rules: PersonaFollowupRules = Field(default_factory=default_followup_rules)


class PersonaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    body_md: str | None = None
    notes: str | None = None
    followup_rules: PersonaFollowupRules | None = None


class ProjectMini(BaseModel):
    """Minimal project representation used in persona assignment lists."""

    id: uuid.UUID
    name: str
    slug: str
