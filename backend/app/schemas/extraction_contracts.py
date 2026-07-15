"""Canonical extraction contracts (Tech-Lead Directive §10).

Versioned JSON schemas that wrap every extracted entity. Parsers/extractors
emit these; validators consume them; publishers persist them to the
authoritative tables (P1-1).

Common envelope::

    {
      "entity_type": "faq"|"bus_timetable"|"benefit"|"working_hours"|"job_requirement",
      "schema_version": "1.0",
      "scope": {"type": "job_posting", "id": "JOB-123"},
      "validity": {"valid_from": "2026-07-01", "valid_to": null, "timezone": "Asia/Ho_Chi_Minh"},
      "data": <entity-specific>,
      "evidence": [<Evidence>, ...],
      "warnings": [<Warning>, ...]
    }

Strict by default: ``extra="forbid"`` rejects unknown fields. Missing data is
``null`` (never inferred). Field validators enforce directive §9 business rules.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Scope(BaseModel):
    """Directive §7 scope: type + id. Resolution precedence (job > location >
    company > global) lives in the tool layer."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["global", "company", "location", "job_posting", "campaign"]
    id: str | None = None


class Validity(BaseModel):
    """Directive §7 validity window."""

    model_config = ConfigDict(extra="forbid")
    valid_from: date | None = None
    valid_to: date | None = None
    timezone: str = "Asia/Ho_Chi_Minh"

    @model_validator(mode="after")
    def _check_range(self) -> Validity:
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from must be on or before valid_to")
        return self


class SourceRef(BaseModel):
    """Directive §11: where an extracted value came from."""

    model_config = ConfigDict(extra="forbid")
    document_id: int | None = None
    page: int | None = None
    fragment_id: int | None = None
    table_row: int | None = None
    table_column: int | None = None


class Evidence(BaseModel):
    """One piece of field-level provenance (directive §11)."""

    model_config = ConfigDict(extra="forbid")
    field_path: str
    value: Any = None
    source: SourceRef = Field(default_factory=SourceRef)
    method: Literal[
        "table_parser", "regex", "llm_extractor", "deterministic", "key_value", "manual"
    ]
    confidence: float = Field(ge=0.0, le=1.0)


class Warning(BaseModel):
    """Soft issue flagged during extraction (non-blocking)."""

    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    field_path: str | None = None


# ─── Per-entity data shapes ──────────────────────────────────────────────────


class FaqData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_question: str = Field(min_length=1)
    # answer is required for static_answer; may be empty for tool resolution
    # (populated dynamically by the tool at query time).
    answer: str = ""
    aliases: list[str] = Field(default_factory=list)
    language: str = Field(default="vi", pattern=r"^[a-z]{2}$")
    resolution_type: Literal["static_answer", "tool"] = "static_answer"
    tool_name: str | None = None

    @model_validator(mode="after")
    def _resolution_consistency(self) -> FaqData:
        if self.resolution_type == "tool":
            if not self.tool_name:
                raise ValueError("resolution_type='tool' requires tool_name")
        else:  # static_answer
            if not self.answer:
                raise ValueError("answer required for resolution_type='static_answer'")
        return self


class BusStopTime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    name: str = Field(min_length=1)
    arrival_time: str | None = None  # "HH:MM:SS"
    departure_time: str | None = None

    @model_validator(mode="after")
    def _at_least_one_time(self) -> BusStopTime:
        if not self.arrival_time and not self.departure_time:
            raise ValueError("at least one of arrival_time/departure_time required")
        return self


class BusTrip(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trip_code: str | None = None
    stops: list[BusStopTime] = Field(min_length=1)

    @model_validator(mode="after")
    def _sequences_unique_and_ordered(self) -> BusTrip:
        seqs = [s.sequence for s in self.stops]
        if len(set(seqs)) != len(seqs):
            raise ValueError("stop sequences must be unique within a trip")
        if seqs != sorted(seqs):
            raise ValueError("stop sequences must be ordered ascending")
        return self


class BusRouteInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1)
    name: str | None = None
    direction: Literal["OUTBOUND", "INBOUND", "ROUNDTRIP"] = "OUTBOUND"


class BusTimetableData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: BusRouteInfo
    service_days: list[Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]] = Field(
        min_length=1
    )
    trips: list[BusTrip] = Field(min_length=1)


class BenefitData(BaseModel):
    """Directive §10 benefit contract + §9 validation rules."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    category: Literal[
        "ALLOWANCE", "INSURANCE", "ACCOMMODATION", "TRANSPORT", "MEAL", "BONUS", "OTHER"
    ]
    value: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")  # ISO 4217
    cadence: Literal["hourly", "daily", "monthly", "annual", "one_time"] | None = None
    eligibility: str | None = None
    taxable: bool | None = None

    @model_validator(mode="after")
    def _value_requires_currency_and_cadence(self) -> BenefitData:
        if self.value is not None:
            if self.currency is None:
                raise ValueError("currency required when value is set")
            if self.cadence is None:
                raise ValueError("cadence required when value is set")
        return self


class BreakPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: str  # "HH:MM:SS"
    end_time: str


class WorkingHoursData(BaseModel):
    """Directive §10 working-hours contract + §9 validation rules."""

    model_config = ConfigDict(extra="forbid")
    schedule_type: Literal["FIXED", "ROTATING", "SHIFT"]
    days: list[Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]]
    start_time: str  # "HH:MM:SS"
    end_time: str
    crosses_midnight: bool = False
    breaks: list[BreakPeriod] = Field(default_factory=list)
    exceptions: list[dict] = Field(default_factory=list)  # opaque here; validated at publishing

    @model_validator(mode="after")
    def _crosses_midnight_consistency(self) -> WorkingHoursData:
        if self.start_time and self.end_time and not self.crosses_midnight:
            # Without midnight crossing, end_time must be > start_time lexically
            # (string comparison works for "HH:MM:SS").
            if self.end_time <= self.start_time:
                raise ValueError("end_time <= start_time requires crosses_midnight=True")
        return self

    @field_validator("days")
    @classmethod
    def _days_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("days must not be empty")
        return v


class JobRequirementData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    category: Literal["age", "experience", "education", "gender", "skill", "document", "other"]
    is_required: bool = True
    min_value: str | None = None
    max_value: str | None = None
    unit: str | None = None


# ─── Discriminated union on entity_type ──────────────────────────────────────


EntityData = Annotated[
    Union[
        FaqData,
        BusTimetableData,
        BenefitData,
        WorkingHoursData,
        JobRequirementData,
    ],
    Field(discriminator="entity_type"),
]


class FaqEnvelopeData(FaqData):
    entity_type: Literal["faq"] = "faq"


class BusTimetableEnvelopeData(BusTimetableData):
    entity_type: Literal["bus_timetable"] = "bus_timetable"


class BenefitEnvelopeData(BenefitData):
    entity_type: Literal["benefit"] = "benefit"


class WorkingHoursEnvelopeData(WorkingHoursData):
    entity_type: Literal["working_hours"] = "working_hours"


class JobRequirementEnvelopeData(JobRequirementData):
    entity_type: Literal["job_requirement"] = "job_requirement"


EnvelopeData = Annotated[
    Union[
        FaqEnvelopeData,
        BusTimetableEnvelopeData,
        BenefitEnvelopeData,
        WorkingHoursEnvelopeData,
        JobRequirementEnvelopeData,
    ],
    Field(discriminator="entity_type"),
]


class ExtractionEnvelope(BaseModel):
    """The common envelope wrapping all extracted entity types (directive §10)."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(pattern=r"^\d+\.\d+$", default="1.0")
    scope: Scope
    validity: Validity = Field(default_factory=Validity)
    data: EnvelopeData
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)


# ─── Validator entry point ───────────────────────────────────────────────────


def validate_contract(payload: dict) -> ExtractionEnvelope:
    """Validate ``payload`` as an ExtractionEnvelope; raises ValueError on invalid.

    Collects ALL validation errors (Pydantic raises ValidationError which carries
    them) so publishers can surface the full list, not just the first.
    """
    from pydantic import ValidationError

    try:
        return ExtractionEnvelope.model_validate(payload)
    except ValidationError as exc:
        # Re-raise with a flattened message so callers don't need to import
        # Pydantic's ValidationError class.
        errors = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ValueError(f"contract validation failed: {errors}") from exc
