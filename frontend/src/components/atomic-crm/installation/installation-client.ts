import { apiRequest } from "../providers/rest/api";
import { z } from "zod";

const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const identifierSchema = z.string().regex(/^[a-z0-9][a-z0-9._-]{0,63}$/);
const modelIdSchema = z
  .string()
  .regex(/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/)
  .refine(
    (value) => !/^(?:sk-|xox|ghp_|github_pat_|aiza)/i.test(value),
    "Model ID must not contain a credential",
  );

export type InstallationIssue = {
  code: string;
  message: string;
  path: string | null;
};

export type IdentityBrandingDraft = {
  customer_identity: {
    display_name: string;
    legal_name?: string;
    support_name?: string;
    support_email?: string;
    support_phone?: string;
    website_url?: string;
    address?: string;
  };
  branding: {
    app_name: string;
    primary_color?: string;
    secondary_color?: string;
  };
};

export type RegionalTerminologyDraft = {
  locale: string;
  timezone: string;
  currency: string;
  terminology: Record<string, string>;
};

export type PackCapabilitiesDraft = {
  pack_key: string;
  capability_ids: string[];
};

export type WorkflowDraft = {
  workflow_policy: {
    workflow_id: string;
    handoff_mode: "manual" | "assisted" | "automatic";
    automation_enabled: boolean;
  };
};

export type KnowledgeTemplatesDraft = {
  template_version_refs: Array<{ version_id: string; checksum: string }>;
};

export type PersonaDraft = {
  persona_version_id: string;
  checksum: string;
};

export type ProvidersIntegrationsDraft = {
  provider_policy: {
    chat_integration_key: string;
    chat_model: string;
    embedding_integration_key: string;
    embedding_model: string;
    temperature: number;
    max_output_tokens: number;
  };
  integration_requirements: Array<{ key: string }>;
  authentication_policy: { email_password_enabled: true };
};

export type InstallationSetupDraftPayload = {
  identity_branding?: IdentityBrandingDraft;
  regional_terminology?: RegionalTerminologyDraft;
  pack_capabilities?: PackCapabilitiesDraft;
  workflow?: WorkflowDraft;
  knowledge_templates?: KnowledgeTemplatesDraft;
  persona?: PersonaDraft;
  providers_integrations?: ProvidersIntegrationsDraft;
};

export type InstallationSetupDraft = {
  payload: InstallationSetupDraftPayload;
  lock_version: number;
  installation_lock_version: number;
  section_completion: Record<string, boolean>;
  issues: InstallationIssue[];
};

export type InstallationCatalogPack = {
  key: string;
  version: string;
  contract_hash: string;
  capability_ids: string[];
  runtime_ready: boolean;
  workflow_ids: string[];
  terminology_keys: string[];
};

export type InstallationCatalog = {
  schema_version: 1;
  packs: InstallationCatalogPack[];
  capabilities: Array<{ id: string; dependencies: string[] }>;
  locales: string[];
  currencies: string[];
  workflows: Array<{
    id: string;
    handoff_modes: Array<"manual" | "assisted" | "automatic">;
  }>;
  integration_keys: string[];
  authentication_methods: "email_password"[];
};

type InstallationErrorEnvelope = {
  detail?: unknown;
  code?: unknown;
  lifecycle?: unknown;
  issues?: unknown;
};

export class InstallationClientError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly lifecycle: string,
    public readonly issues: InstallationIssue[],
    public readonly expectedLockVersion?: number,
    public readonly submittedDraft?: InstallationSetupDraftPayload,
  ) {
    super(message);
    this.name = "InstallationClientError";
  }
}

const issueSchema = z
  .object({
    code: z.string(),
    message: z.string(),
    path: z.string().nullable(),
  })
  .strict();

const setupDraftPayloadSchema = z
  .object({
    identity_branding: z
      .object({
        customer_identity: z
          .object({
            display_name: z.string().min(1).max(160),
            legal_name: z.string().max(240).optional(),
            support_name: z.string().max(160).optional(),
            support_email: z.string().email().max(254).optional(),
            support_phone: z.string().max(32).optional(),
            website_url: z.string().url().max(500).refine((value) => /^https?:\/\//i.test(value)).optional(),
            address: z.string().max(500).optional(),
          })
          .strict(),
        branding: z
          .object({
            app_name: z.string().min(1).max(160).refine((value) => value.trim().length > 0),
            primary_color: z.string().regex(/^#[0-9a-fA-F]{6}$/).optional(),
            secondary_color: z.string().regex(/^#[0-9a-fA-F]{6}$/).optional(),
          })
          .strict(),
      })
      .strict()
      .nullable()
      .optional(),
    regional_terminology: z
      .object({
        locale: z.string().regex(/^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?$/),
        timezone: z.string().min(1).max(64),
        currency: z.string().regex(/^[A-Z]{3}$/),
        terminology: z.record(z.string(), z.string().min(1).max(80).refine((item) => item.trim().length > 0)),
      })
      .strict()
      .nullable()
      .optional(),
    pack_capabilities: z
      .object({
        pack_key: identifierSchema,
        capability_ids: z.array(identifierSchema),
      })
      .strict()
      .nullable()
      .optional(),
    workflow: z
      .object({
        workflow_policy: z
          .object({
            workflow_id: identifierSchema,
            handoff_mode: z.enum(["manual", "assisted", "automatic"]),
            automation_enabled: z.boolean(),
          })
          .strict(),
      })
      .strict()
      .nullable()
      .optional(),
    knowledge_templates: z
      .object({
        template_version_refs: z.array(
          z.object({ version_id: z.string().uuid(), checksum: sha256Schema }).strict(),
        ),
      })
      .strict()
      .nullable()
      .optional(),
    persona: z
      .object({
        persona_version_id: z.string().uuid(),
        checksum: sha256Schema,
      })
      .strict()
      .nullable()
      .optional(),
    providers_integrations: z
      .object({
        provider_policy: z
          .object({
            chat_integration_key: identifierSchema,
            chat_model: modelIdSchema,
            embedding_integration_key: identifierSchema,
            embedding_model: modelIdSchema,
            temperature: z.number().min(0).max(2),
            max_output_tokens: z.number().int().min(1).max(131_072),
          })
          .strict(),
        integration_requirements: z.array(z.object({ key: identifierSchema }).strict()),
        authentication_policy: z
          .object({ email_password_enabled: z.literal(true) })
          .strict(),
      })
      .strict()
      .nullable()
      .optional(),
  })
  .strict()
  .transform((raw): InstallationSetupDraftPayload => {
    const payload: InstallationSetupDraftPayload = {};
    for (const key of [
      "identity_branding",
      "regional_terminology",
      "pack_capabilities",
      "workflow",
      "knowledge_templates",
      "persona",
      "providers_integrations",
    ] as const) {
      const value = raw[key];
      if (value != null) Object.assign(payload, { [key]: value });
    }
    return payload;
  });

const setupDraftSchema = z
  .object({
    payload: setupDraftPayloadSchema,
    lock_version: z.number().int().nonnegative(),
    installation_lock_version: z.number().int().nonnegative(),
    section_completion: z.record(z.string(), z.boolean()),
    issues: z.array(issueSchema),
  })
  .strict();

const catalogSchema = z
  .object({
    schema_version: z.literal(1),
    packs: z.array(
      z
        .object({
          key: identifierSchema,
          version: z.string().min(1).max(32),
          contract_hash: sha256Schema,
          capability_ids: z.array(identifierSchema),
          runtime_ready: z.boolean(),
          workflow_ids: z.array(identifierSchema),
          terminology_keys: z.array(identifierSchema),
        })
        .strict(),
    ),
    capabilities: z.array(
      z.object({ id: identifierSchema, dependencies: z.array(identifierSchema) }).strict(),
    ),
    locales: z.array(z.string()),
    currencies: z.array(z.string()),
    workflows: z.array(
      z
        .object({
          id: identifierSchema,
          handoff_modes: z.array(z.enum(["manual", "assisted", "automatic"])),
        })
        .strict(),
    ),
    integration_keys: z.array(identifierSchema),
    authentication_methods: z.array(z.literal("email_password")).length(1),
  })
  .strict();

const validationSchema = z
  .object({
    id: z.string().uuid(),
    revision_id: z.string().uuid(),
    validator_version: z.string(),
    is_valid: z.boolean(),
    issues: z.array(issueSchema),
    manifest_checksum: sha256Schema,
    pack_contract_hash: sha256Schema,
    persona_checksum: sha256Schema,
    workflow_policy_checksum: sha256Schema,
    provider_policy_checksum: sha256Schema,
    authentication_policy_checksum: sha256Schema.nullable(),
    template_checksums: z.record(z.string(), sha256Schema),
    active_kb_vector: z.array(z.array(z.string())),
    created_at: z.string(),
  })
  .strict();

const revisionSchema = z
  .object({
    id: z.string().uuid(),
    revision_no: z.number().int().positive(),
    predecessor_id: z.string().uuid().nullable(),
    pack_key: identifierSchema,
    pack_version: z.string(),
    pack_contract_hash: sha256Schema,
    manifest_checksum: sha256Schema,
    customer_identity: z.record(z.string(), z.unknown()),
    branding: z.record(z.string(), z.unknown()),
    locale: z.string(),
    timezone: z.string(),
    currency: z.string(),
    terminology: z.record(z.string(), z.unknown()),
    workflow_policy: z.record(z.string(), z.unknown()),
    workflow_policy_checksum: sha256Schema,
    capability_ids: z.array(identifierSchema),
    persona_version_id: z.string().uuid(),
    template_version_refs: z.array(
      z.object({ version_id: z.string().uuid(), checksum: sha256Schema }).strict(),
    ),
    provider_policy: z.record(z.string(), z.unknown()),
    provider_policy_checksum: sha256Schema,
    integration_requirements: z.array(z.object({ key: identifierSchema }).strict()),
    authentication_policy: z
      .object({ email_password_enabled: z.literal(true) })
      .strict()
      .nullable(),
    authentication_policy_checksum: sha256Schema.nullable(),
    created_by: z.string().uuid().nullable(),
    created_at: z.string(),
  })
  .strict();

const installationAdminStatusSchema = z
  .object({
    lifecycle: z.enum([
      "UNCONFIGURED",
      "DRAFT",
      "VALIDATED",
      "ACTIVE",
      "SUSPENDED",
      "UPGRADE_REQUIRED",
    ]),
    authority_generation: z.number().int().nonnegative(),
    lock_version: z.number().int().nonnegative(),
    current_revision: revisionSchema.nullable(),
    active_revision_id: z.string().uuid().nullable(),
    active_validation: validationSchema.nullable(),
    current_validation: validationSchema.nullable(),
    readiness_code: z.string(),
  })
  .strict();

export type InstallationAdminStatus = z.infer<typeof installationAdminStatusSchema>;

const isIssue = (value: unknown): value is InstallationIssue => {
  if (!value || typeof value !== "object") return false;
  const issue = value as Record<string, unknown>;
  return (
    typeof issue.code === "string" &&
    typeof issue.message === "string" &&
    (typeof issue.path === "string" || issue.path === null)
  );
};

const requestInstallationJson = async <T>(
  path: string,
  init: RequestInit = {},
  conflictContext?: {
    expectedLockVersion: number;
    submittedDraft: InstallationSetupDraftPayload;
  },
  parse?: (value: unknown) => T,
): Promise<T> => {
  const response = await apiRequest(path, {
    method: init.method,
    headers: init.headers as Record<string, string> | undefined,
    body:
      typeof init.body === "string"
        ? (JSON.parse(init.body) as Record<string, unknown>)
        : undefined,
  });
  if (!response.ok) {
    let envelope: InstallationErrorEnvelope = {};
    try {
      envelope = (await response.json()) as InstallationErrorEnvelope;
    } catch {
      // Stable fallback fields below keep transport failures typed.
    }
    throw new InstallationClientError(
      typeof envelope.detail === "string" ? envelope.detail : "Installation request failed",
      response.status,
      typeof envelope.code === "string" ? envelope.code : "INSTALLATION_REQUEST_FAILED",
      typeof envelope.lifecycle === "string" ? envelope.lifecycle : "UNKNOWN",
      Array.isArray(envelope.issues) ? envelope.issues.filter(isIssue) : [],
      conflictContext?.expectedLockVersion,
      conflictContext?.submittedDraft,
    );
  }
  const value: unknown = await response.json();
  return parse ? parse(value) : (value as T);
};

export const getInstallationSetupDraft = (): Promise<InstallationSetupDraft> =>
  requestInstallationJson(
    "/api/v1/admin/installation/setup-draft",
    {},
    undefined,
    (value) => setupDraftSchema.parse(value),
  );

export const getInstallationCatalog = (): Promise<InstallationCatalog> =>
  requestInstallationJson(
    "/api/v1/admin/installation/catalog",
    {},
    undefined,
    (value) => catalogSchema.parse(value),
  );

export const getInstallationAdminStatus = (): Promise<InstallationAdminStatus> =>
  requestInstallationJson(
    "/api/v1/admin/installation",
    {},
    undefined,
    (value) => installationAdminStatusSchema.parse(value),
  );

export const saveInstallationSetupDraft = (
  payload: InstallationSetupDraftPayload,
  expectedLockVersion: number,
): Promise<InstallationSetupDraft> => {
  const submittedDraft = structuredClone(payload);
  return requestInstallationJson(
    "/api/v1/admin/installation/setup-draft",
    {
      method: "PUT",
      body: JSON.stringify({
        payload: submittedDraft,
        expected_lock_version: expectedLockVersion,
      }),
    },
    { expectedLockVersion, submittedDraft },
    (value) => setupDraftSchema.parse(value),
  );
};

export type FinalizeSetupDraftInput = {
  expectedDraftLockVersion: number;
  expectedInstallationLockVersion: number;
};

export type InstallationRevisionReference = {
  id: string;
};

export const finalizeInstallationSetupDraft = ({
  expectedDraftLockVersion,
  expectedInstallationLockVersion,
}: FinalizeSetupDraftInput): Promise<InstallationRevisionReference> =>
  requestInstallationJson(
    "/api/v1/admin/installation/setup-draft/finalize",
    {
      method: "POST",
      body: JSON.stringify({
        expected_draft_lock_version: expectedDraftLockVersion,
        expected_installation_lock_version: expectedInstallationLockVersion,
      }),
    },
    undefined,
    (value) => ({ id: revisionSchema.parse(value).id }),
  );
