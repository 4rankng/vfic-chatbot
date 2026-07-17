import type {
  ContributionContract,
  FrontendCapabilityRegistry,
} from "./types";
import { RECRUITMENT_V1_PARITY } from "./recruitment-parity";

const contribution = (
  value: ContributionContract,
): ContributionContract => Object.freeze(value);

const contributions = [
  contribution({
    id: "kernel.resource.conversations",
    kind: "resource",
    moduleId: "kernel.workspace.v1",
    resourceName: "conversations",
  }),
  contribution({
    id: "kernel.resource.bot-runs",
    kind: "resource",
    moduleId: "kernel.workspace.v1",
    resourceName: "bot_runs",
  }),
  contribution({
    id: "kernel.resource.knowledge-sources",
    kind: "resource",
    moduleId: "kernel.workspace.v1",
    resourceName: "knowledge_sources",
  }),
  contribution({ id: "kernel.resource.knowledge-bases", kind: "resource", moduleId: "kernel.workspace.v1", resourceName: "knowledge_bases" }),
  contribution({
    id: "kernel.resource.projects",
    kind: "resource",
    moduleId: "kernel.workspace.v1",
    resourceName: "projects",
  }),
  contribution({
    id: "kernel.resource.personas",
    kind: "resource",
    moduleId: "kernel.workspace.v1",
    resourceName: "personas",
  }),
  contribution({
    id: "kernel.resource.settings",
    kind: "resource",
    moduleId: "kernel.workspace.v1",
    resourceName: "settings",
  }),
  contribution({
    id: "kernel.resource.users",
    kind: "resource",
    moduleId: "kernel.workspace.v1",
    resourceName: "users",
  }),
  contribution({
    id: "kernel.route.performance",
    kind: "route",
    moduleId: "kernel.workspace.v1",
    routePath: "/hieu-suat",
    routeLayout: "layout",
  }),
  contribution({
    id: "kernel.route.profile",
    kind: "route",
    moduleId: "kernel.workspace.v1",
    routePath: "/profile",
    routeLayout: "layout",
  }),
  contribution({
    id: "kernel.route.settings-profile-redirect",
    kind: "route",
    moduleId: "kernel.workspace.v1",
    routePath: "/settings/profile",
    routeLayout: "layout",
  }),
  contribution({
    id: "channel.zalo.route.legacy-settings-redirect",
    kind: "route",
    moduleId: "kernel.workspace.v1",
    routePath: "/zalo_integrations/*",
    routeLayout: "layout",
  }),
  contribution({
    id: "kernel.route.forgot-password",
    kind: "route",
    moduleId: "kernel.workspace.v1",
    routePath: "/forgot-password",
    routeLayout: "no-layout",
  }),
  ...(["overview", "messages", "projects", "settings", "performance", "account"] as const).map(
    (id) =>
      contribution({
        id: `kernel.navigation.${id}`,
        kind: "navigation",
        moduleId: "kernel.workspace.v1",
        navigationPath:
          id === "overview"
            ? "/"
            : id === "messages"
              ? "/conversations"
              : id === "performance"
                ? "/hieu-suat"
                : id === "account"
                  ? "/profile"
                  : `/${id}`,
      }),
  ),
  contribution({
    id: "recruitment.dashboard.attention",
    kind: "dashboard",
    moduleId: "recruitment.compat.v1",
    dashboardOwner: "job_advisory",
  }),
  ...(["row", "filters", "context", "actions"] as const).map((slot) =>
    contribution({
      id: `recruitment.conversation.${slot}`,
      kind: "conversation-slot",
      moduleId: "recruitment.compat.v1",
      conversationSlot: slot,
    }),
  ),
] as const;

export const frontendCapabilityRegistry: FrontendCapabilityRegistry = Object.freeze({
  kernelAbi: "1",
  packs: Object.freeze({
    recruitment: Object.freeze({
      key: RECRUITMENT_V1_PARITY.packKey,
      version: RECRUITMENT_V1_PARITY.packVersion,
      kernelAbi: RECRUITMENT_V1_PARITY.kernelAbi,
      contractHash: RECRUITMENT_V1_PARITY.packContractHash,
      parityChecksum: RECRUITMENT_V1_PARITY.parityChecksum,
      capabilityIds: RECRUITMENT_V1_PARITY.capabilityIds,
      baseContributionIds: [
        "kernel.resource.bot-runs",
        "kernel.resource.users",
        "kernel.route.performance",
        "kernel.route.profile",
        "kernel.route.settings-profile-redirect",
        "kernel.route.forgot-password",
        "kernel.navigation.performance",
        "kernel.navigation.account",
      ],
      contributionOrder: [
        "kernel.resource.conversations",
        "kernel.resource.bot-runs",
        "kernel.resource.knowledge-sources",
        "kernel.resource.knowledge-bases",
        "kernel.resource.projects",
        "kernel.resource.personas",
        "kernel.resource.settings",
        "kernel.resource.users",
        "kernel.route.performance",
        "kernel.route.profile",
        "kernel.route.settings-profile-redirect",
        "channel.zalo.route.legacy-settings-redirect",
        "kernel.route.forgot-password",
        "kernel.navigation.overview",
        "kernel.navigation.messages",
        "kernel.navigation.projects",
        "kernel.navigation.settings",
        "kernel.navigation.performance",
        "kernel.navigation.account",
        "recruitment.dashboard.attention",
        "recruitment.conversation.row",
        "recruitment.conversation.filters",
        "recruitment.conversation.context",
        "recruitment.conversation.actions",
      ],
      supportedLocales: ["vi-VN"],
      terminologyKeys: [
        "application",
        "candidate",
        "conversation",
        "job",
        "lead",
        "organization",
      ],
    }),
  }),
  capabilities: Object.freeze({
    conversation: Object.freeze({
      id: "conversation",
      dependencies: [],
      contributionIds: [
        "kernel.resource.conversations",
        "kernel.navigation.messages",
      ],
    }),
    knowledge: Object.freeze({
      id: "knowledge",
      dependencies: ["conversation"],
      contributionIds: [
        "kernel.resource.knowledge-sources",
        "kernel.resource.knowledge-bases",
        "kernel.resource.projects",
        "kernel.resource.personas",
        "kernel.navigation.projects",
      ],
    }),
    candidate_intake: Object.freeze({
      id: "candidate_intake",
      dependencies: ["conversation"],
      contributionIds: [
        "recruitment.conversation.row",
        "recruitment.conversation.filters",
        "recruitment.conversation.context",
        "recruitment.conversation.actions",
      ],
    }),
    job_advisory: Object.freeze({
      id: "job_advisory",
      dependencies: ["candidate_intake", "knowledge"],
      contributionIds: [
        "recruitment.dashboard.attention",
        "kernel.navigation.overview",
      ],
    }),
    "channel.zalo": Object.freeze({
      id: "channel.zalo",
      dependencies: ["conversation"],
      contributionIds: [
        "kernel.resource.settings",
        "channel.zalo.route.legacy-settings-redirect",
        "kernel.navigation.settings",
      ],
    }),
  }),
  contributions: Object.freeze(
    Object.fromEntries(contributions.map((item) => [item.id, item])),
  ),
  moduleLoaders: Object.freeze({
    "kernel.workspace.v1": async () => import("./kernel"),
    "recruitment.compat.v1": async () => import("./recruitment"),
  }),
});
