"""Strict admin inputs and safe public installation projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


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
SHIPPED_LOCALES = ("vi-VN",)
TERMINOLOGY_KEYS = frozenset(
    {"application", "candidate", "case", "contact", "conversation", "job", "lead", "organization"}
)
SETUP_SECTION_NAMES = (
    "identity_branding",
    "regional_terminology",
    "pack_capabilities",
    "workflow",
    "knowledge_templates",
    "persona",
    "providers_integrations",
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


class AuthenticationPolicySettings(BaseModel):
    """Closed authentication policy for currently implemented login methods."""

    model_config = ConfigDict(extra="forbid")

    email_password_enabled: Literal[True]


class TemplateVersionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class IntegrationRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")


class CustomerIdentitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=160)
    legal_name: str | None = Field(default=None, max_length=240)
    support_name: str | None = Field(default=None, max_length=160)
    support_email: EmailStr | None = Field(default=None, max_length=254)
    support_phone: str | None = Field(default=None, max_length=32)
    website_url: AnyHttpUrl | None = Field(default=None, max_length=500)
    address: str | None = Field(default=None, max_length=500)


class BrandingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_name: str = Field(min_length=1, max_length=160)

    @field_validator("app_name")
    @classmethod
    def validate_app_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("app_name must contain visible characters")
        return value

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
    authentication_policy: AuthenticationPolicySettings

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

    @field_validator("locale")
    @classmethod
    def validate_shipped_locale(cls, value: str) -> str:
        if value not in SHIPPED_LOCALES:
            raise ValueError("locale must be one of the shipped locale catalogs")
        return value

    @field_validator("terminology")
    @classmethod
    def validate_terminology(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = set(value) - TERMINOLOGY_KEYS
        if unknown:
            raise ValueError(f"unknown terminology keys: {sorted(unknown)}")
        if any(not item.strip() or len(item) > 80 for item in value.values()):
            raise ValueError("terminology values must contain 1 to 80 visible characters")
        return value

    @field_validator("template_version_refs")
    @classmethod
    def validate_unique_template_versions(
        cls, value: list[TemplateVersionReference]
    ) -> list[TemplateVersionReference]:
        version_ids = [item.version_id for item in value]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError("template_version_refs must contain unique version_id values")
        return value


class IdentityBrandingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_identity: CustomerIdentitySettings
    branding: BrandingSettings


class RegionalTerminologyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str
    timezone: str
    currency: str
    terminology: dict[str, str]

    @model_validator(mode="after")
    def validate_region(self) -> "RegionalTerminologyDraft":
        InstallationRevisionCreate.validate_shipped_locale(self.locale)
        InstallationRevisionCreate.validate_timezone(self.timezone)
        InstallationRevisionCreate.validate_currency(self.currency)
        InstallationRevisionCreate.validate_terminology(self.terminology)
        return self


class PackCapabilitiesDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    capability_ids: list[str]


class WorkflowDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_policy: WorkflowPolicySettings


class KnowledgeTemplatesDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_version_refs: list[TemplateVersionReference]

    @field_validator("template_version_refs")
    @classmethod
    def validate_unique_template_versions(
        cls, value: list[TemplateVersionReference]
    ) -> list[TemplateVersionReference]:
        version_ids = [item.version_id for item in value]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError("template_version_refs must contain unique version_id values")
        return value


class PersonaDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_version_id: uuid.UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProvidersIntegrationsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_policy: ProviderPolicySettings
    integration_requirements: list[IntegrationRequirement]
    authentication_policy: AuthenticationPolicySettings


class InstallationSetupDraftPayload(BaseModel):
    """Strict partial setup state. Missing sections are explicit, never defaulted."""

    model_config = ConfigDict(extra="forbid")

    identity_branding: IdentityBrandingDraft | None = None
    regional_terminology: RegionalTerminologyDraft | None = None
    pack_capabilities: PackCapabilitiesDraft | None = None
    workflow: WorkflowDraft | None = None
    knowledge_templates: KnowledgeTemplatesDraft | None = None
    persona: PersonaDraft | None = None
    providers_integrations: ProvidersIntegrationsDraft | None = None

    def complete(self) -> bool:
        return all(getattr(self, section) is not None for section in SETUP_SECTION_NAMES)

    def to_revision_create(self, *, expected_lock_version: int) -> InstallationRevisionCreate:
        if not self.complete():
            raise ValueError("all setup sections are required before finalization")
        identity = self.identity_branding
        region = self.regional_terminology
        pack = self.pack_capabilities
        workflow = self.workflow
        templates = self.knowledge_templates
        persona = self.persona
        providers = self.providers_integrations
        assert identity and region and pack and workflow and templates and persona and providers
        return InstallationRevisionCreate(
            expected_lock_version=expected_lock_version,
            pack_key=pack.pack_key,
            customer_identity=identity.customer_identity,
            branding=identity.branding,
            locale=region.locale,
            timezone=region.timezone,
            currency=region.currency,
            terminology=region.terminology,
            workflow_policy=workflow.workflow_policy,
            capability_ids=pack.capability_ids,
            persona_version_id=persona.persona_version_id,
            template_version_refs=templates.template_version_refs,
            provider_policy=providers.provider_policy,
            integration_requirements=providers.integration_requirements,
            authentication_policy=providers.authentication_policy,
        )


class InstallationSetupDraftSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: InstallationSetupDraftPayload
    expected_lock_version: int = Field(ge=0)


class InstallationSetupDraftFinalize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_lock_version: int = Field(ge=0)
    expected_installation_lock_version: int = Field(ge=0)


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
    authentication_policy: AuthenticationPolicySettings | None
    authentication_policy_checksum: str | None
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
    authentication_policy_checksum: str | None
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
    current_validation: InstallationValidationOut | None
    readiness_code: str


class InstallationRuntimeOut(BaseModel):
    """Public, non-secret projection used before login and by the shell UI."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    lifecycle: str
    authority_generation: int
    revision_id: uuid.UUID | None
    pack_key: str | None
    pack_version: str | None
    pack_contract_hash: str | None
    manifest_checksum: str | None
    customer_identity: dict[str, JsonValue] | None
    branding: dict[str, JsonValue] | None
    locale: str | None
    timezone: str | None
    currency: str | None
    terminology: dict[str, JsonValue] | None
    capability_ids: list[str]
    readiness_code: str


class InstallationSetupDraftOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: InstallationSetupDraftPayload
    lock_version: int
    installation_lock_version: int
    section_completion: dict[str, bool]
    issues: list[InstallationIssue]


class CapabilityCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dependencies: list[str]


class PackCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    version: str
    contract_hash: str
    capability_ids: list[str]
    runtime_ready: bool
    workflow_ids: list[str]
    terminology_keys: list[str]


class WorkflowCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    handoff_modes: list[Literal["manual", "assisted", "automatic"]]


class InstallationCatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    packs: list[PackCatalogItem]
    capabilities: list[CapabilityCatalogItem]
    locales: list[str]
    currencies: list[str]
    workflows: list[WorkflowCatalogItem]
    integration_keys: list[str]
    authentication_methods: list[Literal["email_password"]]


class InstallationErrorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str
    code: str
    lifecycle: str
    issues: list[InstallationIssue]
