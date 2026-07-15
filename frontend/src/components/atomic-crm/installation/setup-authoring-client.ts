import { z } from "zod";

import { ApiError, apiJson, apiRequest } from "../providers/rest/api";

const uuidSchema = z.string().uuid();
const checksumSchema = z.string().regex(/^[0-9a-f]{64}$/);

const personaOptionSchema = z
  .object({ id: uuidSchema, name: z.string().min(1) });
const personaListSchema = z
  .object({ data: z.array(personaOptionSchema), total: z.number().int().nonnegative() })
  .strict();
const personaVersionSchema = z
  .object({
    id: uuidSchema,
    version_no: z.number().int().positive(),
    checksum: checksumSchema,
    created_at: z.string(),
  })
  .strict();
const personaVersionsSchema = z.object({ data: z.array(personaVersionSchema) }).strict();

export type PersonaOption = z.infer<typeof personaOptionSchema>;
export type PersonaVersionOption = z.infer<typeof personaVersionSchema>;

type DisabledSetupFollowupRule = {
  enabled: false;
  cadence_hours: [];
  eligible_stages: [];
};

export type DisabledSetupFollowupRules = {
  hot: DisabledSetupFollowupRule;
  warm: DisabledSetupFollowupRule;
  not_interested: DisabledSetupFollowupRule;
};

export const listSetupPersonas = async (): Promise<PersonaOption[]> => {
  const value = await apiJson<unknown>("/api/v1/knowledge/personas?per_page=100");
  return personaListSchema.parse(value).data;
};

export const createSetupPersona = async (input: {
  name: string;
  body_md: string;
  notes: string | null;
  followup_rules: DisabledSetupFollowupRules;
}): Promise<PersonaOption> => {
  const value = await apiJson<unknown>("/api/v1/knowledge/personas", {
    method: "POST",
    body: input,
  });
  return personaOptionSchema.parse(value);
};

export const getSetupPersonaTemplate = async (): Promise<string> => {
  const response = await apiRequest("/api/v1/knowledge/personas/format/template");
  if (!response.ok) {
    throw new ApiError(response.status, "Không tải được mẫu Agent.");
  }
  return response.text();
};

export const listSetupPersonaVersions = async (
  personaId: string,
): Promise<PersonaVersionOption[]> => {
  const value = await apiJson<unknown>(
    `/api/v1/personas/${encodeURIComponent(personaId)}/versions`,
  );
  return personaVersionsSchema.parse(value).data;
};

const templateSchema = z
  .object({
    id: uuidSchema,
    template_key: z.string(),
    name: z.string(),
    vertical: z.string(),
    created_at: z.string(),
  })
  .strict();
const templateVersionSchema = z
  .object({
    id: uuidSchema,
    template_id: uuidSchema,
    version_no: z.number().int().positive(),
    status: z.enum(["DRAFT", "PUBLISHED", "DEPRECATED", "REVOKED"]),
    definition: z.record(z.string(), z.unknown()),
    compiled_artifact: z.record(z.string(), z.unknown()).nullable().optional(),
    checksum: checksumSchema.nullable().optional(),
    compiler_version: z.string().nullable().optional(),
    preview_checksum: checksumSchema.nullable().optional(),
    revision: z.number().int().positive(),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();
const previewSchema = z
  .object({
    checksum: checksumSchema,
    records: z.array(z.record(z.string(), z.unknown())),
    issues: z.array(
      z
        .object({
          severity: z.string(),
          code: z.string(),
          message: z.string(),
        })
        .passthrough(),
    ),
  })
  .strict();

export type SetupTemplate = z.infer<typeof templateSchema>;
export type SetupTemplateVersion = z.infer<typeof templateVersionSchema>;
export type SetupTemplatePreview = z.infer<typeof previewSchema>;

export const listSetupTemplates = async (): Promise<SetupTemplate[]> =>
  templateSchema
    .array()
    .parse(await apiJson<unknown>("/api/v1/knowledge/ingestion-templates"));

export const listSetupTemplateVersions = async (
  templateId: string,
): Promise<SetupTemplateVersion[]> =>
  templateVersionSchema.array().parse(
    await apiJson<unknown>(
      `/api/v1/knowledge/ingestion-templates/${encodeURIComponent(templateId)}/versions`,
    ),
  );

export const previewNewSetupTemplate = async (
  definition: Record<string, unknown>,
  sourceText: string,
): Promise<SetupTemplatePreview> =>
  previewSchema.parse(
    await apiJson<unknown>("/api/v1/knowledge/ingestion-templates/preview", {
      method: "POST",
      body: { definition, source_text: sourceText },
    }),
  );

export const createSetupTemplate = async (input: {
  template_key: string;
  name: string;
  vertical: string;
  definition: Record<string, unknown>;
}): Promise<SetupTemplateVersion> =>
  templateVersionSchema.parse(
    await apiJson<unknown>("/api/v1/knowledge/ingestion-templates", {
      method: "POST",
      body: input,
    }),
  );

export const previewSetupTemplateVersion = async (
  versionId: string,
  sourceText: string,
): Promise<SetupTemplatePreview> =>
  previewSchema.parse(
    await apiJson<unknown>(
      `/api/v1/knowledge/ingestion-template-versions/${encodeURIComponent(versionId)}/preview`,
      { method: "POST", body: { source_text: sourceText } },
    ),
  );

export const publishSetupTemplateVersion = async (
  versionId: string,
): Promise<SetupTemplateVersion> =>
  templateVersionSchema.parse(
    await apiJson<unknown>(
      `/api/v1/knowledge/ingestion-template-versions/${encodeURIComponent(versionId)}/publish`,
      { method: "POST" },
    ),
  );

export type SecretStatus = { configured: boolean; preview?: string | null };

const secretStatusSchema = z
  .object({ configured: z.boolean(), preview: z.string().nullable().optional() })
  .strict();

const providerStatusSchemas = {
  minimax: z
    .object({
      minimax_api_key: secretStatusSchema,
      minimax_base_url: z.string(),
      minimax_agent_model: z.string(),
      minimax_safety_model: z.string(),
      minimax_enable: z.boolean(),
      llm_default_provider: z.enum(["minimax", "openrouter"]),
    })
    .strict(),
  openrouter: z
    .object({
      openrouter_api_key: secretStatusSchema,
      openrouter_base_url: z.string(),
      openrouter_agent_model: z.string(),
      openrouter_safety_model: z.string(),
      openrouter_digest_model: z.string(),
      openrouter_embedding_model: z.string(),
      openrouter_embedding_dim: z.number().int().positive(),
      openrouter_enable: z.boolean(),
      llm_default_provider: z.enum(["minimax", "openrouter"]),
    })
    .strict(),
} as const;

export type SupportedModelIntegration = keyof typeof providerStatusSchemas;

export const isSupportedModelIntegration = (
  value: string,
): value is SupportedModelIntegration => value === "minimax" || value === "openrouter";

export const getModelIntegrationStatus = async (key: SupportedModelIntegration) =>
  providerStatusSchemas[key].parse(
    await apiJson<unknown>(`/api/v1/admin/integrations/${key}`),
  );

export const saveModelIntegrationSecret = async (
  key: SupportedModelIntegration,
  secret: string,
): Promise<void> => {
  const secretField = key === "minimax" ? "minimax_api_key" : "openrouter_api_key";
  providerStatusSchemas[key].parse(
    await apiJson<unknown>(`/api/v1/admin/integrations/${key}`, {
      method: "PUT",
      body: { [secretField]: secret, [`${key}_enable`]: true },
    }),
  );
};

const integrationTestSchema = z
  .object({ configured: z.boolean(), missing: z.array(z.string()) })
  .strict();

export const testModelIntegration = async (
  key: SupportedModelIntegration,
): Promise<{ configured: boolean; missing: string[] }> =>
  integrationTestSchema.parse(
    await apiJson<unknown>(`/api/v1/admin/integrations/${key}/test`, {
      method: "POST",
    }),
  );

const plainStatusSchema = z
  .object({ configured: z.boolean(), value: z.string().nullable().optional() })
  .strict();
const zaloStatusSchema = z
  .object({
    zalo_bot_token: secretStatusSchema,
    zalo_bot_webhook_secret: secretStatusSchema,
    zalo_oa_app_id: plainStatusSchema,
    zalo_oa_secret_key: secretStatusSchema,
    zalo_oa_access_token: secretStatusSchema,
    zalo_oa_refresh_token: secretStatusSchema,
    zalo_bot_api_base: z.string(),
    zalo_oa_api_base: z.string(),
    zalo_oa_webhook_signature: z.unknown().nullable(),
    zalo_bot_webhook_sync: z.unknown().nullable().optional(),
  })
  .strict();

export type ZaloSetupStatus = z.infer<typeof zaloStatusSchema>;
export type ZaloSecretDraft = {
  zalo_bot_token: string;
  zalo_bot_webhook_secret: string;
  zalo_oa_app_id: string;
  zalo_oa_secret_key: string;
  zalo_oa_access_token: string;
  zalo_oa_refresh_token: string;
};

export const getZaloSetupStatus = async (): Promise<ZaloSetupStatus> =>
  zaloStatusSchema.parse(
    await apiJson<unknown>("/api/v1/admin/integrations/zalo"),
  );

export const saveZaloSetupSecrets = async (
  input: Partial<ZaloSecretDraft>,
): Promise<ZaloSetupStatus> =>
  zaloStatusSchema.parse(
    await apiJson<unknown>("/api/v1/admin/integrations/zalo", {
      method: "PUT",
      body: input,
    }),
  );

const zaloTestSchema = z
  .object({
    configured: z.boolean(),
    connected: z.boolean(),
    missing: z.array(z.string()),
    errors: z.array(z.string()),
  })
  .passthrough();

export const testZaloSetupChannel = async (
  channel: "bot" | "oa",
): Promise<{ configured: boolean; connected: boolean; missing: string[]; errors: string[] }> =>
  zaloTestSchema.parse(
    await apiJson<unknown>(`/api/v1/admin/integrations/zalo/${channel}/test`, {
      method: "POST",
    }),
  );
