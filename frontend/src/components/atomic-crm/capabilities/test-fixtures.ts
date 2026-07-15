import type { PublicRuntimeManifest } from "../installation/runtime-manifest";
import type { FrontendCapabilityRegistry } from "./types";
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

export const genericFixtureManifest = (
  overrides: Partial<PublicRuntimeManifest> = {},
): PublicRuntimeManifest =>
  readyRecruitmentManifest({
    pack_key: "generic-fixture",
    pack_contract_hash: "c".repeat(64),
    capability_ids: ["conversation"],
    ...overrides,
  });

export const genericFixtureRegistry = (
  genericLoader: FrontendCapabilityRegistry["moduleLoaders"][string] = async () =>
    import("./generic"),
  recruitmentLoader: FrontendCapabilityRegistry["moduleLoaders"][string] = async () =>
    import("./recruitment"),
): FrontendCapabilityRegistry => ({
  kernelAbi: "1",
  packs: {
    "generic-fixture": {
      key: "generic-fixture",
      version: "1",
      kernelAbi: "1",
      contractHash: "c".repeat(64),
      parityChecksum: "c".repeat(64),
      capabilityIds: ["conversation"],
      baseContributionIds: [
        "kernel.resource.contacts",
        "kernel.resource.cases",
        "kernel.resource.generic-conversations",
        "kernel.resource.generic-users",
        "kernel.dashboard.generic",
        "kernel.route.workflow-authoring",
        "kernel.route.generic-profile",
      ],
      supportedLocales: ["vi-VN"],
      terminologyKeys: ["contact", "case"],
    },
  },
  capabilities: {
    conversation: {
      id: "conversation",
      dependencies: [],
      contributionIds: [],
    },
  },
  contributions: {
    "kernel.resource.contacts": {
      id: "kernel.resource.contacts",
      kind: "resource",
      moduleId: "kernel.generic.fixture",
      resourceName: "contacts",
    },
    "kernel.resource.cases": {
      id: "kernel.resource.cases",
      kind: "resource",
      moduleId: "kernel.generic.fixture",
      resourceName: "cases",
    },
    "kernel.resource.generic-conversations": {
      id: "kernel.resource.generic-conversations",
      kind: "resource",
      moduleId: "kernel.generic.fixture",
      resourceName: "conversations",
    },
    "kernel.resource.generic-users": {
      id: "kernel.resource.generic-users",
      kind: "resource",
      moduleId: "kernel.generic.fixture",
      resourceName: "users",
    },
    "kernel.dashboard.generic": {
      id: "kernel.dashboard.generic",
      kind: "dashboard",
      moduleId: "kernel.generic.fixture",
      dashboardOwner: "kernel",
    },
    "kernel.route.workflow-authoring": {
      id: "kernel.route.workflow-authoring",
      kind: "route",
      moduleId: "kernel.generic.fixture",
      routePath: "/settings/workflows/new",
      routeLayout: "layout",
    },
    "kernel.route.generic-profile": {
      id: "kernel.route.generic-profile",
      kind: "route",
      moduleId: "kernel.generic.fixture",
      routePath: "/profile",
      routeLayout: "layout",
    },
  },
  moduleLoaders: {
    "kernel.generic.fixture": genericLoader,
    "recruitment.compat.v1": recruitmentLoader,
  },
});
