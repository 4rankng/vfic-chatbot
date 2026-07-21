"""Strict YAML contracts for the twelve project-owned RAG categories.

Project scope is supplied by the upload endpoint.  These contracts therefore
never accept a factory or project identifier.  A category document is a full
replacement of that category, and stable IDs make its derived rows repeatable.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator


StableId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
NonEmptyText = Annotated[str, Field(min_length=1, max_length=5000)]
MAX_CATEGORY_RECORDS = 1_000


class KnowledgeCategoryKey(StrEnum):
    JOBS = "jobs"
    COMPENSATION = "compensation"
    REQUIREMENTS = "requirements"
    WORK_SCHEDULES = "work_schedules"
    BENEFITS = "benefits"
    ACCOMMODATION = "accommodation"
    MEALS = "meals"
    TRANSPORTATION = "transportation"
    INSURANCE = "insurance"
    APPLICATION = "application"
    CONTACTS = "contacts"
    FAQ = "faq"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CategoryDocument(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    category: KnowledgeCategoryKey


def _ensure_unique_ids(records: list[object]) -> None:
    identifiers = [getattr(record, "id") for record in records]
    duplicates = sorted(value for value, count in Counter(identifiers).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate stable id(s): {', '.join(duplicates)}")


class JobItem(StrictModel):
    id: StableId
    title: NonEmptyText
    aliases: list[str] = Field(default_factory=list, max_length=30)
    location: str | None = Field(default=None, max_length=500)
    vacancies: StrictInt | None = Field(default=None, ge=1)
    employment_type: Literal["permanent", "temporary", "contract", "internship"] | None = None
    summary: str | None = Field(default=None, max_length=5000)
    keywords: list[str] = Field(default_factory=list, max_length=50)


class JobsDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.JOBS] = KnowledgeCategoryKey.JOBS
    jobs: list[JobItem] = Field(default_factory=list, max_length=MAX_CATEGORY_RECORDS)

    @model_validator(mode="after")
    def validate_ids(self) -> JobsDocument:
        _ensure_unique_ids(self.jobs)
        return self


class MoneyItem(StrictModel):
    name: NonEmptyText
    amount_vnd: StrictInt = Field(ge=0)
    cadence: Literal["hour", "shift", "day", "week", "month", "year", "one_time"]
    conditions: str | None = Field(default=None, max_length=2000)


class CompensationItem(StrictModel):
    id: StableId
    job_ids: list[StableId] = Field(default_factory=list)
    base_salary_vnd: StrictInt | None = Field(default=None, ge=0)
    estimated_income_min_vnd: StrictInt | None = Field(default=None, ge=0)
    estimated_income_max_vnd: StrictInt | None = Field(default=None, ge=0)
    allowances: list[MoneyItem] = Field(default_factory=list)
    bonuses: list[MoneyItem] = Field(default_factory=list)
    overtime_notes: str | None = Field(default=None, max_length=3000)
    payment_notes: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def validate_income_range(self) -> CompensationItem:
        if (
            self.estimated_income_min_vnd is not None
            and self.estimated_income_max_vnd is not None
            and self.estimated_income_min_vnd > self.estimated_income_max_vnd
        ):
            raise ValueError("estimated income minimum must not exceed maximum")
        return self


class CompensationDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.COMPENSATION] = KnowledgeCategoryKey.COMPENSATION
    compensation: list[CompensationItem] = Field(
        default_factory=list, max_length=MAX_CATEGORY_RECORDS
    )

    @model_validator(mode="after")
    def validate_ids(self) -> CompensationDocument:
        _ensure_unique_ids(self.compensation)
        return self


class RequirementItem(StrictModel):
    id: StableId
    job_ids: list[StableId] = Field(default_factory=list)
    age_min: StrictInt | None = Field(default=None, ge=15, le=80)
    age_max: StrictInt | None = Field(default=None, ge=15, le=80)
    genders: list[Literal["female", "male", "any"]] = Field(default_factory=list)
    education: str | None = Field(default=None, max_length=1000)
    experience: str | None = Field(default=None, max_length=1000)
    health: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_age_range(self) -> RequirementItem:
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("age_min must not exceed age_max")
        return self


class RequirementsDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.REQUIREMENTS] = KnowledgeCategoryKey.REQUIREMENTS
    requirements: list[RequirementItem] = Field(
        default_factory=list, max_length=MAX_CATEGORY_RECORDS
    )

    @model_validator(mode="after")
    def validate_ids(self) -> RequirementsDocument:
        _ensure_unique_ids(self.requirements)
        return self


class ShiftItem(StrictModel):
    name: NonEmptyText
    start_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    crosses_midnight: StrictBool = False


class WorkScheduleItem(StrictModel):
    id: StableId
    job_ids: list[StableId] = Field(default_factory=list)
    work_days: list[str] = Field(default_factory=list)
    shifts: list[ShiftItem] = Field(default_factory=list)
    rotation: str | None = Field(default=None, max_length=2000)
    breaks: list[str] = Field(default_factory=list)
    overtime: str | None = Field(default=None, max_length=3000)
    notes: str | None = Field(default=None, max_length=3000)


class WorkSchedulesDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.WORK_SCHEDULES] = KnowledgeCategoryKey.WORK_SCHEDULES
    work_schedules: list[WorkScheduleItem] = Field(
        default_factory=list, max_length=MAX_CATEGORY_RECORDS
    )

    @model_validator(mode="after")
    def validate_ids(self) -> WorkSchedulesDocument:
        _ensure_unique_ids(self.work_schedules)
        return self


class BenefitItem(StrictModel):
    id: StableId
    job_ids: list[StableId] = Field(default_factory=list)
    name: NonEmptyText
    description: str | None = Field(default=None, max_length=3000)
    eligibility: str | None = Field(default=None, max_length=2000)


class BenefitsDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.BENEFITS] = KnowledgeCategoryKey.BENEFITS
    benefits: list[BenefitItem] = Field(default_factory=list, max_length=MAX_CATEGORY_RECORDS)

    @model_validator(mode="after")
    def validate_ids(self) -> BenefitsDocument:
        _ensure_unique_ids(self.benefits)
        return self


class AccommodationItem(StrictModel):
    id: StableId
    job_ids: list[StableId] = Field(default_factory=list)
    available: StrictBool
    type: str | None = Field(default=None, max_length=500)
    address: str | None = Field(default=None, max_length=1000)
    monthly_cost_vnd: StrictInt | None = Field(default=None, ge=0)
    deposit_vnd: StrictInt | None = Field(default=None, ge=0)
    included_services: list[str] = Field(default_factory=list)
    eligibility: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=3000)


class AccommodationDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.ACCOMMODATION] = KnowledgeCategoryKey.ACCOMMODATION
    accommodation: list[AccommodationItem] = Field(
        default_factory=list, max_length=MAX_CATEGORY_RECORDS
    )

    @model_validator(mode="after")
    def validate_ids(self) -> AccommodationDocument:
        _ensure_unique_ids(self.accommodation)
        return self


class MealItem(StrictModel):
    id: StableId
    job_ids: list[StableId] = Field(default_factory=list)
    provided: StrictBool
    meals_per_shift: StrictInt | None = Field(default=None, ge=0, le=10)
    allowance_vnd: StrictInt | None = Field(default=None, ge=0)
    menu_notes: str | None = Field(default=None, max_length=3000)
    eligibility: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=3000)


class MealsDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.MEALS] = KnowledgeCategoryKey.MEALS
    meals: list[MealItem] = Field(default_factory=list, max_length=MAX_CATEGORY_RECORDS)

    @model_validator(mode="after")
    def validate_ids(self) -> MealsDocument:
        _ensure_unique_ids(self.meals)
        return self


class BusStopItem(StrictModel):
    order: StrictInt = Field(ge=1)
    name: NonEmptyText
    time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    address: str | None = Field(default=None, max_length=1000)


class TransportationItem(StrictModel):
    id: StableId
    job_ids: list[StableId] = Field(default_factory=list)
    name: NonEmptyText
    direction: Literal["to_factory", "from_factory", "round_trip"]
    service_days: list[str] = Field(default_factory=list)
    shift: str | None = Field(default=None, max_length=200)
    fee_vnd: StrictInt | None = Field(default=None, ge=0)
    stops: list[BusStopItem] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def validate_stop_order(self) -> TransportationItem:
        orders = [stop.order for stop in self.stops]
        if len(orders) != len(set(orders)):
            raise ValueError("bus stop order must be unique within a route")
        if orders != sorted(orders):
            raise ValueError("bus stops must be ordered by ascending order")
        return self


class TransportationDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.TRANSPORTATION] = KnowledgeCategoryKey.TRANSPORTATION
    transportation: list[TransportationItem] = Field(
        default_factory=list, max_length=MAX_CATEGORY_RECORDS
    )

    @model_validator(mode="after")
    def validate_ids(self) -> TransportationDocument:
        _ensure_unique_ids(self.transportation)
        return self


class InsuranceItem(StrictModel):
    id: StableId
    job_ids: list[StableId] = Field(default_factory=list)
    name: NonEmptyText
    provider: str | None = Field(default=None, max_length=500)
    employee_contribution: str | None = Field(default=None, max_length=1000)
    employer_contribution: str | None = Field(default=None, max_length=1000)
    coverage: list[str] = Field(default_factory=list)
    starts_after: str | None = Field(default=None, max_length=1000)
    eligibility: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=3000)


class InsuranceDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.INSURANCE] = KnowledgeCategoryKey.INSURANCE
    insurance: list[InsuranceItem] = Field(default_factory=list, max_length=MAX_CATEGORY_RECORDS)

    @model_validator(mode="after")
    def validate_ids(self) -> InsuranceDocument:
        _ensure_unique_ids(self.insurance)
        return self


class ApplicationItem(StrictModel):
    id: StableId
    job_ids: list[StableId] = Field(default_factory=list)
    application_steps: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    interview_location: str | None = Field(default=None, max_length=1000)
    interview_process: str | None = Field(default=None, max_length=3000)
    onboarding_steps: list[str] = Field(default_factory=list)
    processing_time: str | None = Field(default=None, max_length=1000)
    fees: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=3000)


class ApplicationDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.APPLICATION] = KnowledgeCategoryKey.APPLICATION
    application: list[ApplicationItem] = Field(
        default_factory=list, max_length=MAX_CATEGORY_RECORDS
    )

    @model_validator(mode="after")
    def validate_ids(self) -> ApplicationDocument:
        _ensure_unique_ids(self.application)
        return self


class ContactItem(StrictModel):
    id: StableId
    name: NonEmptyText
    role: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=50)
    zalo: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    address: str | None = Field(default=None, max_length=1000)
    working_hours: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=3000)


class ContactsDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.CONTACTS] = KnowledgeCategoryKey.CONTACTS
    contacts: list[ContactItem] = Field(default_factory=list, max_length=MAX_CATEGORY_RECORDS)

    @model_validator(mode="after")
    def validate_ids(self) -> ContactsDocument:
        _ensure_unique_ids(self.contacts)
        return self


class FaqItem(StrictModel):
    id: StableId
    question: NonEmptyText
    answer: NonEmptyText
    tags: list[str] = Field(default_factory=list, max_length=50)
    question_variants: list[str] = Field(default_factory=list, max_length=50)
    required_terms: list[str] = Field(default_factory=list, max_length=50)
    forbidden_terms: list[str] = Field(default_factory=list, max_length=50)


class FaqDocument(CategoryDocument):
    category: Literal[KnowledgeCategoryKey.FAQ] = KnowledgeCategoryKey.FAQ
    faq: list[FaqItem] = Field(default_factory=list, max_length=MAX_CATEGORY_RECORDS)

    @model_validator(mode="after")
    def validate_ids(self) -> FaqDocument:
        _ensure_unique_ids(self.faq)
        return self


CategoryDocumentType = (
    JobsDocument
    | CompensationDocument
    | RequirementsDocument
    | WorkSchedulesDocument
    | BenefitsDocument
    | AccommodationDocument
    | MealsDocument
    | TransportationDocument
    | InsuranceDocument
    | ApplicationDocument
    | ContactsDocument
    | FaqDocument
)


CATEGORY_DOCUMENT_MODELS: dict[KnowledgeCategoryKey, type[CategoryDocument]] = {
    KnowledgeCategoryKey.JOBS: JobsDocument,
    KnowledgeCategoryKey.COMPENSATION: CompensationDocument,
    KnowledgeCategoryKey.REQUIREMENTS: RequirementsDocument,
    KnowledgeCategoryKey.WORK_SCHEDULES: WorkSchedulesDocument,
    KnowledgeCategoryKey.BENEFITS: BenefitsDocument,
    KnowledgeCategoryKey.ACCOMMODATION: AccommodationDocument,
    KnowledgeCategoryKey.MEALS: MealsDocument,
    KnowledgeCategoryKey.TRANSPORTATION: TransportationDocument,
    KnowledgeCategoryKey.INSURANCE: InsuranceDocument,
    KnowledgeCategoryKey.APPLICATION: ApplicationDocument,
    KnowledgeCategoryKey.CONTACTS: ContactsDocument,
    KnowledgeCategoryKey.FAQ: FaqDocument,
}
