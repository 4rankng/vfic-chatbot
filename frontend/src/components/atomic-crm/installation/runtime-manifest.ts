import { z } from "zod";
import { apiUrl } from "../providers/rest/api";
import { RECRUITMENT_V1_PARITY } from "../capabilities/recruitment-parity";

const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const nullableSha256Schema = sha256Schema.nullable();
const nullableUuidSchema = z.string().uuid().nullable();

/**
 * Wraps an optional string field that the backend serializes as JSON null
 * when unset. Accepts string | null | absent and normalizes null to
 * undefined so the inferred type stays `string | undefined`.
 */
const nullableOptional = <S extends z.ZodTypeAny>(schema: S) =>
  schema.nullish().transform((value) => value ?? undefined);

const customerIdentitySchema = z
  .object({
    display_name: z.string().min(1).max(160),
    legal_name: nullableOptional(z.string().max(240)),
    support_name: nullableOptional(z.string().max(160)),
    support_email: nullableOptional(z.string().email().max(254)),
    support_phone: nullableOptional(z.string().max(32)),
    website_url: nullableOptional(z.string().url().max(500)),
    address: nullableOptional(z.string().max(500)),
  })
  .strict();

const brandingSchema = z
  .object({
    app_name: nullableOptional(z.string().max(160)),
    primary_color: nullableOptional(z.string().regex(/^#[0-9a-fA-F]{6}$/)),
    secondary_color: nullableOptional(z.string().regex(/^#[0-9a-fA-F]{6}$/)),
  })
  .strict();

const runtimeManifestSchema = z
  .object({
    schema_version: z.literal(1),
    lifecycle: z.enum([
      "UNCONFIGURED",
      "DRAFT",
      "VALIDATED",
      "ACTIVE",
      "SUSPENDED",
      "UPGRADE_REQUIRED",
    ]),
    authority_generation: z.number().int().nonnegative(),
    revision_id: nullableUuidSchema,
    pack_key: z.string().regex(/^[a-z0-9][a-z0-9._-]*$/).nullable(),
    pack_version: z.string().min(1).max(32).nullable(),
    pack_contract_hash: nullableSha256Schema,
    manifest_checksum: nullableSha256Schema,
    customer_identity: customerIdentitySchema.nullable(),
    branding: brandingSchema.nullable(),
    locale: z.string().min(2).max(35).nullable(),
    timezone: z.string().min(1).max(64).nullable(),
    currency: z.string().regex(/^[A-Z]{3}$/).nullable(),
    terminology: z.record(z.string(), z.string()).nullable(),
    capability_ids: z.array(z.string().regex(/^[a-z0-9][a-z0-9._-]*$/)),
    legacy_workspace: z.boolean().default(false),
    readiness_code: z.enum([
      "SETUP_REQUIRED",
      "RUNTIME_NOT_READY",
      "READY",
      "SUSPENDED",
      "UPGRADE_REQUIRED",
      "VALIDATION_REQUIRED",
    ]),
  })
  .strict()
  .superRefine((manifest, context) => {
    const authorityFields = [
      manifest.revision_id,
      manifest.pack_key,
      manifest.pack_version,
      manifest.pack_contract_hash,
      manifest.manifest_checksum,
      manifest.customer_identity,
      manifest.branding,
      manifest.locale,
      manifest.timezone,
      manifest.currency,
      manifest.terminology,
    ];
    const hasCompleteAuthority = authorityFields.every((value) => value !== null);
    const hasNoAuthority = authorityFields.every((value) => value === null);

    if (
      ["ACTIVE", "SUSPENDED", "UPGRADE_REQUIRED"].includes(manifest.lifecycle) &&
      !hasCompleteAuthority
    ) {
      context.addIssue({
        code: "custom",
        message: "Runtime lifecycle requires complete authority evidence",
      });
    }
    if (
      ["UNCONFIGURED", "DRAFT", "VALIDATED"].includes(manifest.lifecycle) &&
      (!hasNoAuthority || manifest.capability_ids.length > 0)
    ) {
      context.addIssue({
        code: "custom",
        message: "Pre-active runtime manifest must not expose draft authority",
      });
    }
    if (manifest.readiness_code === "READY" && manifest.lifecycle !== "ACTIVE") {
      context.addIssue({
        code: "custom",
        message: "Only an ACTIVE installation may report READY",
      });
    }
    const allowedReadiness: Record<PublicRuntimeManifest["lifecycle"], readonly string[]> = {
      UNCONFIGURED: ["SETUP_REQUIRED"],
      DRAFT: ["SETUP_REQUIRED"],
      VALIDATED: ["SETUP_REQUIRED", "RUNTIME_NOT_READY"],
      ACTIVE: ["READY", "VALIDATION_REQUIRED", "RUNTIME_NOT_READY"],
      SUSPENDED: ["SUSPENDED", "RUNTIME_NOT_READY"],
      UPGRADE_REQUIRED: ["UPGRADE_REQUIRED"],
    };
    if (!allowedReadiness[manifest.lifecycle].includes(manifest.readiness_code)) {
      context.addIssue({
        code: "custom",
        message: "Runtime lifecycle and readiness are inconsistent",
      });
    }
    if (
      manifest.legacy_workspace &&
      (manifest.lifecycle !== "UNCONFIGURED" || manifest.readiness_code !== "SETUP_REQUIRED")
    ) {
      context.addIssue({
        code: "custom",
        message: "Legacy workspace compatibility applies only before installation setup",
      });
    }
  });

export type PublicRuntimeManifest = z.infer<typeof runtimeManifestSchema>;

export class RuntimeManifestError extends Error {
  constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "RuntimeManifestError";
  }
}

export const parseRuntimeManifest = (value: unknown): PublicRuntimeManifest => {
  const result = runtimeManifestSchema.safeParse(value);
  if (!result.success) {
    throw new RuntimeManifestError("Invalid installation runtime manifest", result.error);
  }
  return result.data;
};

export const isLegacyWorkspaceRuntime = (manifest: PublicRuntimeManifest): boolean =>
  manifest.lifecycle === "UNCONFIGURED" &&
  manifest.readiness_code === "SETUP_REQUIRED" &&
  manifest.legacy_workspace;

/**
 * Temporary display-only composition for installations that predate the
 * installation lifecycle. It does not declare backend runtime authority or
 * alter bot dispatch; it preserves the established recruitment console until
 * the workspace is explicitly adopted into the lifecycle.
 */
export const legacyRecruitmentWorkspaceManifest = (): PublicRuntimeManifest => ({
  schema_version: 1,
  lifecycle: "ACTIVE",
  authority_generation: 0,
  revision_id: "00000000-0000-4000-8000-000000000001",
  pack_key: RECRUITMENT_V1_PARITY.packKey,
  pack_version: RECRUITMENT_V1_PARITY.packVersion,
  pack_contract_hash: RECRUITMENT_V1_PARITY.packContractHash,
  manifest_checksum: "0".repeat(64),
  customer_identity: {
    display_name: "Ting Ting",
    legal_name: undefined,
    support_name: undefined,
    support_email: undefined,
    support_phone: undefined,
    website_url: undefined,
    address: undefined,
  },
  branding: {
    app_name: "Ting Ting",
    primary_color: undefined,
    secondary_color: undefined,
  },
  locale: "vi-VN",
  timezone: "Asia/Ho_Chi_Minh",
  currency: "VND",
  terminology: {},
  capability_ids: [...RECRUITMENT_V1_PARITY.capabilityIds],
  readiness_code: "READY",
  legacy_workspace: false,
});

type FetchRuntimeManifestOptions = {
  timeoutMs?: number;
};

export const fetchRuntimeManifest = async (
  options: FetchRuntimeManifestOptions = {},
): Promise<PublicRuntimeManifest> => {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs ?? 5_000);
  try {
    const response = await fetch(apiUrl("/api/v1/installation/runtime"), {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      credentials: "same-origin",
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new RuntimeManifestError(
        `Installation runtime request failed with status ${response.status}`,
      );
    }
    const cacheControl = response.headers.get("Cache-Control")?.toLowerCase() ?? "";
    if (!cacheControl.includes("no-store")) {
      throw new RuntimeManifestError("Installation runtime response is cacheable");
    }
    return parseRuntimeManifest(await response.json());
  } finally {
    window.clearTimeout(timeout);
  }
};
