import { z } from "zod";
import { apiUrl } from "../providers/rest/api";

const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const nullableSha256Schema = sha256Schema.nullable();
const nullableUuidSchema = z.string().uuid().nullable();

const customerIdentitySchema = z
  .object({
    display_name: z.string().min(1).max(160),
    legal_name: z.string().max(240).optional(),
    support_name: z.string().max(160).optional(),
    support_email: z.string().email().max(254).optional(),
    support_phone: z.string().max(32).optional(),
    website_url: z.string().url().max(500).optional(),
    address: z.string().max(500).optional(),
  })
  .strict();

const brandingSchema = z
  .object({
    app_name: z.string().max(160).optional(),
    primary_color: z.string().regex(/^#[0-9a-fA-F]{6}$/).optional(),
    secondary_color: z.string().regex(/^#[0-9a-fA-F]{6}$/).optional(),
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
