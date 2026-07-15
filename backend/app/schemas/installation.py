"""Strict admin inputs and safe public installation projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


ISO_4217_CURRENCY_CODES = frozenset(
    "AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BHD BIF BMD BND BOB BOV BRL BSD "
    "BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP CVE CZK DJF DKK "
    "DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF "
    "IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP "
    "LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD "
    "NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR "
    "SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS "
    "UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAD XAF XAG XAU XBA XBB XBC "
    "XBD XCD XCG XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG".split()
)


class WorkflowPolicySettings(BaseModel):
    """Bounded, declarative workflow choices; never executable configuration."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    handoff_mode: Literal["manual", "assisted", "automatic"]
    automation_enabled: bool


class ProviderPolicySettings(BaseModel):
    """Non-secret model routing that references encrypted integration records."""

    model_config = ConfigDict(extra="forbid")

    chat_integration_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    chat_model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    embedding_integration_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    embedding_model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    temperature: float = Field(ge=0, le=2)
    max_output_tokens: int = Field(ge=1, le=131_072)

    @field_validator("chat_model", "embedding_model")
    @classmethod
    def reject_secret_shaped_model_values(cls, value: str) -> str:
        lowered = value.lower()
        if lowered.startswith(("sk-", "xox", "ghp_", "github_pat_", "aiza")):
            raise ValueError("model selection must not contain a credential value")
        return value


class TemplateVersionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class IntegrationRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)


class CustomerIdentitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=160)
    legal_name: str | None = Field(default=None, max_length=240)
    support_name: str | None = Field(default=None, max_length=160)
    support_email: str | None = Field(default=None, max_length=254)
    support_phone: str | None = Field(default=None, max_length=32)
    website_url: str | None = Field(default=None, max_length=500)
    address: str | None = Field(default=None, max_length=500)


class BrandingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_name: str | None = Field(default=None, max_length=160)
    logo_url: str | None = Field(default=None, max_length=500)
    favicon_url: str | None = Field(default=None, max_length=500)
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    secondary_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class InstallationRevisionCreate(BaseModel):
    """Complete installation input; no business value is inferred by the server."""

    model_config = ConfigDict(extra="forbid")

    expected_lock_version: int = Field(ge=0)
    pack_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    customer_identity: CustomerIdentitySettings
    branding: BrandingSettings
    locale: str = Field(
        min_length=2,
        max_length=35,
        pattern=r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?$",
    )
    timezone: str = Field(min_length=1, max_length=64)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    terminology: dict[str, str]
    workflow_policy: WorkflowPolicySettings
    capability_ids: list[str]
    persona_version_id: uuid.UUID
    template_version_refs: list[TemplateVersionReference]
    provider_policy: ProviderPolicySettings
    integration_requirements: list[IntegrationRequirement]

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA name") from exc
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value not in ISO_4217_CURRENCY_CODES:
            raise ValueError("currency must be a current ISO 4217 alphabetic code")
        return value


class InstallationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    path: str | None = None


class InstallationRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    revision_no: int
    predecessor_id: uuid.UUID | None
    pack_key: str
    pack_version: str
    pack_contract_hash: str
    manifest_checksum: str
    customer_identity: dict[str, JsonValue]
    branding: dict[str, JsonValue]
    locale: str
    timezone: str
    currency: str
    terminology: dict[str, JsonValue]
    workflow_policy: dict[str, JsonValue]
    workflow_policy_checksum: str
    capability_ids: list[str]
    persona_version_id: uuid.UUID
    template_version_refs: list[TemplateVersionReference]
    provider_policy: dict[str, JsonValue]
    provider_policy_checksum: str
    integration_requirements: list[IntegrationRequirement]
    created_by: uuid.UUID | None
    created_at: datetime


class InstallationValidationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    revision_id: uuid.UUID
    validator_version: str
    is_valid: bool
    issues: list[InstallationIssue]
    manifest_checksum: str
    pack_contract_hash: str
    persona_checksum: str
    workflow_policy_checksum: str
    provider_policy_checksum: str
    template_checksums: dict[str, str]
    active_kb_vector: list[list[str]]
    created_at: datetime


class InstallationAdminOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle: str
    authority_generation: int
    lock_version: int
    current_revision: InstallationRevisionOut | None
    active_revision_id: uuid.UUID | None
    active_validation: InstallationValidationOut | None
    readiness_code: str


class InstallationRuntimeOut(BaseModel):
    """Public, non-secret projection used before login and by the shell UI."""

    model_config = ConfigDict(extra="forbid")

    lifecycle: str
    authority_generation: int
    revision_id: uuid.UUID | None
    pack_key: str | None
    customer_identity: dict[str, JsonValue] | None
    branding: dict[str, JsonValue] | None
    locale: str | None
    timezone: str | None
    currency: str | None
    terminology: dict[str, JsonValue] | None
    capability_ids: list[str]
    readiness_code: str


class InstallationErrorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str
    code: str
    lifecycle: str
    issues: list[InstallationIssue]
