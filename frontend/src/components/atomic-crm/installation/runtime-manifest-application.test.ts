import { describe, expect, it } from "vitest";

import {
  loadRuntimeManifest,
  type RuntimeManifestGateway,
} from "./runtime-manifest-application";
import { RuntimeManifestError } from "./runtime-manifest-policy";

const activeManifest = {
  schema_version: 1,
  lifecycle: "ACTIVE" as const,
  authority_generation: 9,
  revision_id: "00000000-0000-4000-8000-000000000009",
  pack_key: "recruitment",
  pack_version: "1.0.0",
  pack_contract_hash: "a".repeat(64),
  manifest_checksum: "b".repeat(64),
  customer_identity: { display_name: "Configured customer" },
  branding: { app_name: "Configured workspace", primary_color: "#115e59" },
  locale: "vi-VN",
  timezone: "Asia/Ho_Chi_Minh",
  currency: "VND",
  terminology: { lead: "Ung vien" },
  capability_ids: ["conversation", "candidate_intake"],
  readiness_code: "READY" as const,
  legacy_workspace: false,
};

const gateway = (overrides?: Partial<Awaited<ReturnType<RuntimeManifestGateway["readRuntimeManifest"]>>>): RuntimeManifestGateway => ({
  readRuntimeManifest: async () => ({
    ok: true,
    status: 200,
    cacheControl: "no-store",
    json: async () => activeManifest,
    ...overrides,
  }),
});

describe("loadRuntimeManifest", () => {
  it("accepts a gateway response with a no-store cache policy", async () => {
    await expect(loadRuntimeManifest(gateway())).resolves.toEqual(activeManifest);
  });

  it("rejects a cacheable runtime response before publishing it", async () => {
    await expect(
      loadRuntimeManifest(gateway({ cacheControl: "public, max-age=60" })),
    ).rejects.toBeInstanceOf(RuntimeManifestError);
  });

  it("surfaces the runtime status on a non-2xx gateway response", async () => {
    await expect(
      loadRuntimeManifest(gateway({ ok: false, status: 503 })),
    ).rejects.toMatchObject({
      message: "Installation runtime request failed with status 503",
    });
  });
});
