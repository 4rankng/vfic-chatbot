import type { PublicRuntimeManifest } from "../installation/runtime-manifest";
import type {
  CompiledDestination,
  CompiledResource,
  CompiledRoute,
  CompiledRuntime,
  CompiledRuntimePlan,
  ConversationSlots,
  ExecutableContribution,
  FrontendCapabilityRegistry,
} from "./types";
import { frontendCapabilityRegistry } from "./registry";

const SHA256 = /^[0-9a-f]{64}$/;
const IDENTIFIER = /^[a-z0-9][a-z0-9._-]*$/;

export class CapabilityCompilationError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "CapabilityCompilationError";
  }
}

function fail(code: string, message: string): never {
  throw new CapabilityCompilationError(code, message);
}

const normalizedPath = (path: string): string => {
  const withoutWildcard = path.replace(/\/\*$/, "");
  const collapsed = withoutWildcard.replace(/\/{2,}/g, "/");
  if (collapsed === "/") return "/";
  return collapsed.replace(/\/$/, "");
};

export const getRuntimeKey = (manifest: PublicRuntimeManifest): string =>
  [
    manifest.schema_version,
    manifest.revision_id,
    manifest.authority_generation,
    manifest.manifest_checksum,
    manifest.pack_key,
    manifest.pack_version,
    manifest.pack_contract_hash,
  ].join(":");

const assertUnique = (values: readonly string[], code: string, label: string): void => {
  const seen = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) fail(code, `Duplicate ${label}: ${value}`);
    seen.add(value);
  }
};

const assertAcyclicDependencies = (
  registry: FrontendCapabilityRegistry,
  capabilityIds: readonly string[],
): void => {
  const selected = new Set(capabilityIds);
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (capabilityId: string): void => {
    if (visiting.has(capabilityId)) {
      fail("DEPENDENCY_CYCLE", `Capability dependency cycle includes ${capabilityId}`);
    }
    if (visited.has(capabilityId)) return;
    const capability = registry.capabilities[capabilityId];
    if (!capability) fail("UNKNOWN_CAPABILITY", `Unknown capability ${capabilityId}`);
    visiting.add(capabilityId);
    for (const dependency of capability.dependencies) {
      if (!selected.has(dependency)) {
        fail(
          "MISSING_DEPENDENCY",
          `Capability ${capabilityId} requires ${dependency}`,
        );
      }
      visit(dependency);
    }
    visiting.delete(capabilityId);
    visited.add(capabilityId);
  };
  capabilityIds.forEach(visit);
};

export const compileCapabilities = (
  manifest: PublicRuntimeManifest,
  registry: FrontendCapabilityRegistry = frontendCapabilityRegistry,
): CompiledRuntimePlan => {
  if (manifest.schema_version !== 1) {
    fail("UNSUPPORTED_SCHEMA", `Unsupported manifest schema ${manifest.schema_version}`);
  }
  if (manifest.lifecycle !== "ACTIVE" || manifest.readiness_code !== "READY") {
    fail("RUNTIME_NOT_READY", "Only an ACTIVE and READY manifest can be compiled");
  }
  const packKey = manifest.pack_key;
  const packVersion = manifest.pack_version;
  const packContractHash = manifest.pack_contract_hash;
  if (!packKey || !packVersion || !packContractHash) {
    fail("INCOMPLETE_AUTHORITY", "Runtime manifest is missing pack authority");
  }
  const pack = registry.packs[packKey];
  if (!pack) fail("UNKNOWN_PACK", `Unknown pack ${packKey}`);
  if (pack.version !== packVersion) {
    fail("UNSUPPORTED_PACK_VERSION", `Unsupported ${pack.key} version`);
  }
  if (pack.kernelAbi !== registry.kernelAbi) {
    fail("UNSUPPORTED_KERNEL_ABI", `Unsupported kernel ABI ${pack.kernelAbi}`);
  }
  if (!SHA256.test(packContractHash) || pack.contractHash !== packContractHash) {
    fail("PACK_HASH_MISMATCH", "Pack contract hash does not match the shipped registry");
  }
  if (!SHA256.test(pack.parityChecksum) || pack.parityChecksum !== pack.contractHash) {
    fail("PARITY_MISMATCH", "Frontend parity artifact does not match the backend pack contract");
  }
  if (!manifest.locale || !pack.supportedLocales.includes(manifest.locale)) {
    fail("UNSUPPORTED_LOCALE", `Unsupported locale ${manifest.locale ?? "null"}`);
  }
  const terminology = manifest.terminology ?? {};
  for (const [key, value] of Object.entries(terminology)) {
    if (!pack.terminologyKeys.includes(key) || !value.trim()) {
      fail("TERMINOLOGY_MISMATCH", `Unsupported terminology entry ${key}`);
    }
  }

  assertUnique(manifest.capability_ids, "DUPLICATE_CAPABILITY", "capability ID");
  const packCapabilities = new Set(pack.capabilityIds);
  for (const capabilityId of manifest.capability_ids) {
    if (!IDENTIFIER.test(capabilityId) || !packCapabilities.has(capabilityId)) {
      fail("CROSS_PACK_CAPABILITY", `Capability ${capabilityId} is not in ${pack.key}`);
    }
  }
  assertAcyclicDependencies(registry, manifest.capability_ids);

  const selectedContributionIds = [
    ...pack.baseContributionIds,
    ...manifest.capability_ids.flatMap((id) => {
      const capability = registry.capabilities[id];
      if (!capability) fail("UNKNOWN_CAPABILITY", `Unknown capability ${id}`);
      return capability.contributionIds;
    }),
  ];
  assertUnique(selectedContributionIds, "DUPLICATE_CONTRIBUTION", "contribution ID");
  const selectedContributions = new Set(selectedContributionIds);
  const contributionIds = pack.contributionOrder
    ? [
        ...pack.contributionOrder.filter((id) => selectedContributions.has(id)),
        ...selectedContributionIds.filter((id) => !pack.contributionOrder!.includes(id)),
      ]
    : selectedContributionIds;
  assertUnique(contributionIds, "DUPLICATE_CONTRIBUTION_ORDER", "ordered contribution ID");

  const resources: string[] = [];
  const routeIds: string[] = [];
  const routePaths: string[] = [];
  const navigationIds: string[] = [];
  const navigationPaths: string[] = [];
  const dashboards: string[] = [];
  const slots: string[] = [];
  for (const id of contributionIds) {
    const item = registry.contributions[id];
    if (!item) fail("UNKNOWN_CONTRIBUTION", `Unknown contribution ${id}`);
    if (!registry.moduleLoaders[item.moduleId]) {
      fail("UNKNOWN_MODULE", `No source-owned loader for ${item.moduleId}`);
    }
    switch (item.kind) {
      case "resource":
        if (!item.resourceName) fail("INVALID_CONTRIBUTION", `${id} has no resource name`);
        resources.push(item.resourceName!);
        break;
      case "route":
        if (!item.routePath || !item.routeLayout) {
          fail("INVALID_CONTRIBUTION", `${id} has an incomplete route contract`);
        }
        routeIds.push(id);
        routePaths.push(normalizedPath(item.routePath!));
        break;
      case "navigation":
        if (!item.navigationPath) {
          fail("INVALID_CONTRIBUTION", `${id} has no navigation path`);
        }
        navigationIds.push(id);
        navigationPaths.push(normalizedPath(item.navigationPath!));
        break;
      case "dashboard":
        dashboards.push(item.dashboardOwner ?? id);
        break;
      case "conversation-slot":
        if (!item.conversationSlot) {
          fail("INVALID_CONTRIBUTION", `${id} has no conversation slot`);
        }
        slots.push(item.conversationSlot!);
        break;
    }
  }
  assertUnique(resources, "RESOURCE_COLLISION", "resource name");
  assertUnique(routeIds, "ROUTE_ID_COLLISION", "route ID");
  assertUnique(routePaths, "ROUTE_PATH_COLLISION", "normalized route path");
  assertUnique(navigationIds, "NAVIGATION_ID_COLLISION", "navigation ID");
  assertUnique(navigationPaths, "NAVIGATION_PATH_COLLISION", "navigation path");
  assertUnique(slots, "CONVERSATION_SLOT_COLLISION", "conversation slot");
  if (dashboards.length !== 1) {
    fail(
      "DASHBOARD_OWNERSHIP",
      `Activatable composition requires one dashboard owner, found ${dashboards.length}`,
    );
  }

  return Object.freeze({
    key: getRuntimeKey(manifest),
    manifest,
    registry,
    contributionIds: Object.freeze([...contributionIds]),
    availableResources: new Set(resources),
  });
};

type MutableConversationSlots = {
  -readonly [Key in keyof ConversationSlots]?: ConversationSlots[Key];
};

const assignSlot = (
  slots: MutableConversationSlots,
  contribution: Extract<ExecutableContribution, { kind: "conversation-slot" }>,
): void => {
  switch (contribution.slot) {
    case "row":
      slots.row = contribution.value as NonNullable<ConversationSlots["row"]>;
      break;
    case "filters":
      slots.filters = contribution.value as NonNullable<ConversationSlots["filters"]>;
      break;
    case "context":
      slots.context = contribution.value as NonNullable<ConversationSlots["context"]>;
      break;
    case "actions":
      slots.actions = contribution.value as NonNullable<ConversationSlots["actions"]>;
      break;
  }
};

export const materializeCompiledRuntime = async (
  plan: CompiledRuntimePlan,
): Promise<CompiledRuntime> => {
  const modules = new Map<string, Awaited<ReturnType<typeof plan.registry.moduleLoaders[string]>>>();
  for (const contributionId of plan.contributionIds) {
    const contract = plan.registry.contributions[contributionId];
    if (!contract) fail("UNKNOWN_CONTRIBUTION", `Unknown contribution ${contributionId}`);
    if (!modules.has(contract.moduleId)) {
      const loader = plan.registry.moduleLoaders[contract.moduleId];
      if (!loader) fail("UNKNOWN_MODULE", `No source-owned loader for ${contract.moduleId}`);
      modules.set(contract.moduleId, await loader());
    }
  }

  const resources: CompiledResource[] = [];
  const routes: CompiledRoute[] = [];
  const navigation: CompiledDestination[] = [];
  const slots: MutableConversationSlots = {};
  let dashboard: CompiledRuntime["dashboard"] | undefined;
  for (const contributionId of plan.contributionIds) {
    const contract = plan.registry.contributions[contributionId]!;
    const executable = modules.get(contract.moduleId)?.contributions[contributionId];
    if (!executable) {
      fail("EXECUTABLE_MISMATCH", `Module did not provide ${contributionId}`);
    }
    if (executable.kind !== contract.kind) {
      fail("EXECUTABLE_MISMATCH", `Module provided the wrong kind for ${contributionId}`);
    }
    switch (executable.kind) {
      case "resource":
        if (
          executable.resource.id !== contributionId ||
          executable.resource.name !== contract.resourceName
        ) {
          fail("EXECUTABLE_MISMATCH", `Resource executable drifted from ${contributionId}`);
        }
        resources.push(executable.resource);
        break;
      case "route":
        if (
          executable.route.id !== contributionId ||
          executable.route.path !== contract.routePath ||
          executable.route.layout !== contract.routeLayout
        ) {
          fail("EXECUTABLE_MISMATCH", `Route executable drifted from ${contributionId}`);
        }
        routes.push(executable.route);
        break;
      case "dashboard":
        if (dashboard) fail("DASHBOARD_OWNERSHIP", "Multiple executable dashboards");
        dashboard = executable.dashboard;
        break;
      case "navigation":
        if (executable.destination.to !== contract.navigationPath) {
          fail("EXECUTABLE_MISMATCH", `Navigation executable drifted from ${contributionId}`);
        }
        navigation.push(executable.destination);
        break;
      case "conversation-slot":
        if (executable.slot !== contract.conversationSlot) {
          fail("EXECUTABLE_MISMATCH", `Conversation slot drifted from ${contributionId}`);
        }
        assignSlot(slots, executable);
        break;
    }
  }
  const selectedDashboard = dashboard;
  if (!selectedDashboard) fail("DASHBOARD_OWNERSHIP", "Executable dashboard is missing");
  return Object.freeze({
    key: plan.key,
    packKey: plan.manifest.pack_key!,
    resources: Object.freeze(resources),
    routes: Object.freeze(routes),
    dashboard: selectedDashboard,
    navigation: Object.freeze(navigation),
    conversationSlots: Object.freeze(slots),
    availableResources: plan.availableResources,
  });
};
