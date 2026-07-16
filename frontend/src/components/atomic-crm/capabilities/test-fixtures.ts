import type { PublicRuntimeManifest } from "../installation/runtime-manifest";
import { RECRUITMENT_V1_PARITY } from "./recruitment-parity";

const uuid = "00000000-0000-4000-8000-000000000001";

export const readyRecruitmentManifest = (
  overrides: Partial<PublicRuntimeManifest> = {},
): PublicRuntimeManifest => ({
  schema_version: 1,
  lifecycle: "ACTIVE",
  authority_generation: 1,
  revision_id: uuid,
  pack_key: "recruitment",
  pack_version: "1",
  pack_contract_hash: RECRUITMENT_V1_PARITY.packContractHash,
  manifest_checksum: "a".repeat(64),
  customer_identity: {
    display_name: "Công ty cấu hình",
    legal_name: undefined,
    support_name: undefined,
    support_email: undefined,
    support_phone: undefined,
    website_url: undefined,
    address: undefined,
  },
  branding: {
    app_name: "Không gian cấu hình",
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
  ...overrides,
});
