import { describe, expect, it, vi } from "vitest";

import {
  CapabilityCompilationError,
  compileCapabilities,
  materializeCompiledRuntime,
} from "./compile-capabilities";
import { frontendCapabilityRegistry } from "./registry";
import { RECRUITMENT_V1_PARITY } from "./recruitment-parity";
import {
  genericFixtureManifest,
  genericFixtureRegistry,
  readyRecruitmentManifest,
} from "./test-fixtures";
import type { ExecutableCapabilityModule, FrontendCapabilityRegistry } from "./types";
import backendRecruitmentContract from "../../../../../backend/app/capabilities/recruitment_v1_contract.json";

const expectCode = (run: () => unknown, code: string): void => {
  try {
    run();
    throw new Error("Expected compilation to fail");
  } catch (error) {
    expect(error).toBeInstanceOf(CapabilityCompilationError);
    expect((error as CapabilityCompilationError).code).toBe(code);
  }
};

describe("compileCapabilities", () => {
  it("matches the canonical backend recruitment contract artifact", () => {
    const backendCapabilities = Object.fromEntries(
      backendRecruitmentContract.pack.capabilities.map((capability) => [
        capability.id,
        capability,
      ]),
    );

    expect(RECRUITMENT_V1_PARITY.packKey).toBe(backendRecruitmentContract.pack.key);
    expect(RECRUITMENT_V1_PARITY.packVersion).toBe(backendRecruitmentContract.pack.version);
    expect(RECRUITMENT_V1_PARITY.kernelAbi).toBe(backendRecruitmentContract.pack.kernel_abi);
    expect(RECRUITMENT_V1_PARITY.packContractHash).toBe(
      backendRecruitmentContract.contract_hash,
    );
    expect([...RECRUITMENT_V1_PARITY.capabilityIds].sort()).toEqual(
      backendRecruitmentContract.pack.capabilities.map(({ id }) => id).sort(),
    );
    expect(frontendCapabilityRegistry.packs.recruitment.terminologyKeys).toEqual(
      backendRecruitmentContract.pack.terminology_keys,
    );
    for (const capabilityId of RECRUITMENT_V1_PARITY.capabilityIds) {
      expect(frontendCapabilityRegistry.capabilities[capabilityId].dependencies).toEqual(
        backendCapabilities[capabilityId]?.dependencies,
      );
    }
  });
  it("preserves the exact recruitment@1 workspace contract", async () => {
    const plan = compileCapabilities(readyRecruitmentManifest());
    const runtime = await materializeCompiledRuntime(plan);

    expect(runtime.resources.map(({ name }) => name)).toEqual([
      "conversations",
      "bot_runs",
      "knowledge_sources",
      "projects",
      "personas",
      "settings",
      "users",
    ]);
    expect(runtime.routes.map(({ path }) => path)).toEqual([
      "/hieu-suat",
      "/profile",
      "/settings/profile",
      "/zalo_integrations/*",
      "/forgot-password",
    ]);
    expect(runtime.navigation.map(({ id }) => id)).toEqual([
      "overview",
      "messages",
      "projects",
      "settings",
      "performance",
      "account",
    ]);
    expect(Object.keys(runtime.conversationSlots).sort()).toEqual([
      "actions",
      "context",
      "filters",
      "row",
    ]);
    expect(typeof runtime.dashboard).toBe("function");
  });

  it("does not invoke a recruitment loader for a generic fixture", async () => {
    const genericLoader = vi.fn(async () => import("./generic"));
    const recruitmentLoader = vi.fn(async () => import("./recruitment"));
    const plan = compileCapabilities(
      genericFixtureManifest(),
      genericFixtureRegistry(genericLoader, recruitmentLoader),
    );
    const runtime = await materializeCompiledRuntime(plan);

    expect(runtime.resources.map(({ name }) => name)).toEqual([
      "contacts",
      "cases",
      "conversations",
      "users",
    ]);
    expect(runtime.conversationSlots).toEqual({});
    expect(genericLoader).toHaveBeenCalledOnce();
    expect(recruitmentLoader).not.toHaveBeenCalled();
  });

  it("rejects executable resource, route, navigation and slot drift from compiled metadata", async () => {
    const genericModule = await import("./generic");
    const resourceContribution = genericModule.contributions["kernel.resource.contacts"];
    const routeContribution = genericModule.contributions["kernel.route.generic-profile"];
    if (resourceContribution?.kind !== "resource" || routeContribution?.kind !== "route") {
      throw new Error("Generic fixture contributions are incomplete");
    }
    const genericDriftRegistry = genericFixtureRegistry(async () => ({
      contributions: {
        ...genericModule.contributions,
        "kernel.resource.contacts": {
          ...resourceContribution,
          resource: { ...resourceContribution.resource, name: "drifted-contacts" },
        },
      },
    }));
    await expect(
      materializeCompiledRuntime(
        compileCapabilities(genericFixtureManifest(), genericDriftRegistry),
      ),
    ).rejects.toMatchObject({ code: "EXECUTABLE_MISMATCH" });

    const routeDriftRegistry = genericFixtureRegistry(async () => ({
      contributions: {
        ...genericModule.contributions,
        "kernel.route.generic-profile": {
          ...routeContribution,
          route: { ...routeContribution.route, layout: "no-layout", path: "/drift" },
        },
      },
    }));
    await expect(
      materializeCompiledRuntime(
        compileCapabilities(genericFixtureManifest(), routeDriftRegistry),
      ),
    ).rejects.toMatchObject({ code: "EXECUTABLE_MISMATCH" });

    const kernelModule = await import("./kernel");
    const navigationContribution = kernelModule.contributions["kernel.navigation.overview"];
    if (navigationContribution?.kind !== "navigation") {
      throw new Error("Recruitment navigation contribution is incomplete");
    }
    const navigationDriftRegistry: FrontendCapabilityRegistry = {
      ...frontendCapabilityRegistry,
      moduleLoaders: {
        ...frontendCapabilityRegistry.moduleLoaders,
        "kernel.workspace.v1": async (): Promise<ExecutableCapabilityModule> => ({
          contributions: {
            ...kernelModule.contributions,
            "kernel.navigation.overview": {
              ...navigationContribution,
              destination: { ...navigationContribution.destination, to: "/drift" },
            },
          },
        }),
      },
    };
    await expect(
      materializeCompiledRuntime(
        compileCapabilities(readyRecruitmentManifest(), navigationDriftRegistry),
      ),
    ).rejects.toMatchObject({ code: "EXECUTABLE_MISMATCH" });

    const recruitmentModule = await import("./recruitment");
    const slotContribution = recruitmentModule.contributions["recruitment.conversation.row"];
    if (slotContribution?.kind !== "conversation-slot") {
      throw new Error("Recruitment slot contribution is incomplete");
    }
    const slotDriftRegistry: FrontendCapabilityRegistry = {
      ...frontendCapabilityRegistry,
      moduleLoaders: {
        ...frontendCapabilityRegistry.moduleLoaders,
        "recruitment.compat.v1": async (): Promise<ExecutableCapabilityModule> => ({
          contributions: {
            ...recruitmentModule.contributions,
            "recruitment.conversation.row": {
              ...slotContribution,
              slot: "filters",
            },
          },
        }),
      },
    };
    await expect(
      materializeCompiledRuntime(
        compileCapabilities(readyRecruitmentManifest(), slotDriftRegistry),
      ),
    ).rejects.toMatchObject({ code: "EXECUTABLE_MISMATCH" });
  });

  it("rejects unknown versions, hashes, capabilities and missing dependencies", () => {
    expectCode(
      () => compileCapabilities(readyRecruitmentManifest({ pack_version: "2" })),
      "UNSUPPORTED_PACK_VERSION",
    );
    expectCode(
      () => compileCapabilities(readyRecruitmentManifest({ pack_contract_hash: "f".repeat(64) })),
      "PACK_HASH_MISMATCH",
    );
    expectCode(
      () => compileCapabilities(readyRecruitmentManifest({ capability_ids: ["unknown"] })),
      "CROSS_PACK_CAPABILITY",
    );
    expectCode(
      () => compileCapabilities(readyRecruitmentManifest({ capability_ids: ["job_advisory"] })),
      "MISSING_DEPENDENCY",
    );
  });

  it("rejects duplicate inputs and unsupported locale or terminology", () => {
    expectCode(
      () =>
        compileCapabilities(
          readyRecruitmentManifest({ capability_ids: ["conversation", "conversation"] }),
        ),
      "DUPLICATE_CAPABILITY",
    );
    expectCode(
      () => compileCapabilities(readyRecruitmentManifest({ locale: "en-US" })),
      "UNSUPPORTED_LOCALE",
    );
    expectCode(
      () => compileCapabilities(readyRecruitmentManifest({ terminology: { unknown: "x" } })),
      "TERMINOLOGY_MISMATCH",
    );
  });

  it("rejects resource, normalized route, dashboard and slot collisions", () => {
    const base = genericFixtureRegistry();
    const collisionRegistry: FrontendCapabilityRegistry = {
      ...base,
      packs: {
        "generic-fixture": {
          ...base.packs["generic-fixture"],
          baseContributionIds: [
            ...base.packs["generic-fixture"].baseContributionIds,
            "duplicate.resource",
          ],
        },
      },
      contributions: {
        ...base.contributions,
        "duplicate.resource": {
          id: "duplicate.resource",
          kind: "resource",
          moduleId: "kernel.generic.fixture",
          resourceName: "contacts",
        },
      },
    };
    expectCode(
      () => compileCapabilities(genericFixtureManifest(), collisionRegistry),
      "RESOURCE_COLLISION",
    );

    const noDashboard: FrontendCapabilityRegistry = {
      ...base,
      packs: {
        "generic-fixture": {
          ...base.packs["generic-fixture"],
          baseContributionIds: base.packs["generic-fixture"].baseContributionIds.filter(
            (id) => id !== "kernel.dashboard.generic",
          ),
        },
      },
    };
    expectCode(
      () => compileCapabilities(genericFixtureManifest(), noDashboard),
      "DASHBOARD_OWNERSHIP",
    );

    const badParity: FrontendCapabilityRegistry = {
      ...frontendCapabilityRegistry,
      packs: {
        ...frontendCapabilityRegistry.packs,
        recruitment: {
          ...frontendCapabilityRegistry.packs.recruitment,
          parityChecksum: "0".repeat(64),
        },
      },
    };
    expectCode(
      () => compileCapabilities(readyRecruitmentManifest(), badParity),
      "PARITY_MISMATCH",
    );
  });

  it("rejects cycles, route/navigation/slot collisions and unknown source contracts", () => {
    const base = genericFixtureRegistry();
    const withPackContributions = (
      ids: readonly string[],
      contributions: FrontendCapabilityRegistry["contributions"],
      moduleLoaders = base.moduleLoaders,
    ): FrontendCapabilityRegistry => ({
      ...base,
      packs: {
        "generic-fixture": {
          ...base.packs["generic-fixture"],
          baseContributionIds: [
            ...base.packs["generic-fixture"].baseContributionIds,
            ...ids,
          ],
        },
      },
      contributions: { ...base.contributions, ...contributions },
      moduleLoaders,
    });

    const cycle: FrontendCapabilityRegistry = {
      ...base,
      capabilities: {
        conversation: {
          ...base.capabilities.conversation,
          dependencies: ["conversation"],
        },
      },
    };
    expectCode(
      () => compileCapabilities(genericFixtureManifest(), cycle),
      "DEPENDENCY_CYCLE",
    );

    const routeCollision = withPackContributions(
      ["duplicate.route"],
      {
        "duplicate.route": {
          id: "duplicate.route",
          kind: "route",
          moduleId: "kernel.generic.fixture",
          routePath: "/profile/",
          routeLayout: "no-layout",
        },
      },
    );
    expectCode(
      () => compileCapabilities(genericFixtureManifest(), routeCollision),
      "ROUTE_PATH_COLLISION",
    );

    const navigationCollision = withPackContributions(
      ["navigation.one", "navigation.two"],
      {
        "navigation.one": {
          id: "navigation.one",
          kind: "navigation",
          moduleId: "kernel.generic.fixture",
          navigationPath: "/contacts",
        },
        "navigation.two": {
          id: "navigation.two",
          kind: "navigation",
          moduleId: "kernel.generic.fixture",
          navigationPath: "/contacts/",
        },
      },
    );
    expectCode(
      () => compileCapabilities(genericFixtureManifest(), navigationCollision),
      "NAVIGATION_PATH_COLLISION",
    );

    const slotCollision = withPackContributions(
      ["slot.one", "slot.two"],
      {
        "slot.one": {
          id: "slot.one",
          kind: "conversation-slot",
          moduleId: "kernel.generic.fixture",
          conversationSlot: "row",
        },
        "slot.two": {
          id: "slot.two",
          kind: "conversation-slot",
          moduleId: "kernel.generic.fixture",
          conversationSlot: "row",
        },
      },
    );
    expectCode(
      () => compileCapabilities(genericFixtureManifest(), slotCollision),
      "CONVERSATION_SLOT_COLLISION",
    );

    const unknownContribution: FrontendCapabilityRegistry = {
      ...base,
      packs: {
        "generic-fixture": {
          ...base.packs["generic-fixture"],
          baseContributionIds: [
            ...base.packs["generic-fixture"].baseContributionIds,
            "missing.contribution",
          ],
        },
      },
    };
    expectCode(
      () => compileCapabilities(genericFixtureManifest(), unknownContribution),
      "UNKNOWN_CONTRIBUTION",
    );

    const unknownModule: FrontendCapabilityRegistry = {
      ...base,
      contributions: {
        ...base.contributions,
        "kernel.resource.contacts": {
          ...base.contributions["kernel.resource.contacts"],
          moduleId: "missing.module",
        },
      },
    };
    expectCode(
      () => compileCapabilities(genericFixtureManifest(), unknownModule),
      "UNKNOWN_MODULE",
    );
  });
});
