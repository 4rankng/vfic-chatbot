import { contributions as kernelContributions } from "./kernel";
import { contributions as recruitmentContributions } from "./recruitment";
import type {
  CompiledDestination,
  CompiledResource,
  CompiledRoute,
  CompiledRuntime,
  ConversationSlots,
  ExecutableContribution,
} from "./types";

const contributions: Readonly<Record<string, ExecutableContribution>> =
  Object.freeze({
    ...kernelContributions,
    ...recruitmentContributions,
  });

const RESOURCE_IDS = [
  "kernel.resource.conversations",
  "kernel.resource.bot-runs",
  "kernel.resource.projects",
  "kernel.resource.settings",
  "kernel.resource.users",
] as const;

const ROUTE_IDS = [
  "kernel.route.performance",
  "kernel.route.profile",
  "kernel.route.settings-profile-redirect",
  "channel.zalo.route.legacy-settings-redirect",
  "kernel.route.forgot-password",
] as const;

const NAVIGATION_IDS = [
  "kernel.navigation.overview",
  "kernel.navigation.messages",
  "kernel.navigation.projects",
  "kernel.navigation.users",
  "kernel.navigation.settings",
  "kernel.navigation.bot_runs",
  "kernel.navigation.performance",
] as const;

const SLOT_IDS = [
  "recruitment.conversation.row",
  "recruitment.conversation.filters",
  "recruitment.conversation.context",
  "recruitment.conversation.actions",
] as const;

const contribution = (id: string): ExecutableContribution => {
  const value = contributions[id];
  if (!value) throw new Error(`Missing static recruitment contribution: ${id}`);
  return value;
};

const resource = (id: string): CompiledResource => {
  const value = contribution(id);
  if (value.kind !== "resource")
    throw new Error(`Expected resource contribution: ${id}`);
  return value.resource;
};

const route = (id: string): CompiledRoute => {
  const value = contribution(id);
  if (value.kind !== "route")
    throw new Error(`Expected route contribution: ${id}`);
  return value.route;
};

const navigation = (id: string): CompiledDestination => {
  const value = contribution(id);
  if (value.kind !== "navigation")
    throw new Error(`Expected navigation contribution: ${id}`);
  return value.destination;
};

const dashboard = () => {
  const value = contribution("recruitment.dashboard.attention");
  if (value.kind !== "dashboard") {
    throw new Error("Expected recruitment dashboard contribution");
  }
  return value.dashboard;
};

const conversationSlots = (): ConversationSlots => {
  const slots: {
    row?: ConversationSlots["row"];
    filters?: ConversationSlots["filters"];
    context?: ConversationSlots["context"];
    actions?: ConversationSlots["actions"];
  } = {};
  for (const id of SLOT_IDS) {
    const value = contribution(id);
    if (value.kind !== "conversation-slot") {
      throw new Error(`Expected conversation-slot contribution: ${id}`);
    }
    switch (value.slot) {
      case "row":
        slots.row = value.value as ConversationSlots["row"];
        break;
      case "filters":
        slots.filters = value.value as ConversationSlots["filters"];
        break;
      case "context":
        slots.context = value.value as ConversationSlots["context"];
        break;
      case "actions":
        slots.actions = value.value as ConversationSlots["actions"];
        break;
    }
  }
  return Object.freeze({
    row: slots.row,
    filters: slots.filters,
    context: slots.context,
    actions: slots.actions,
  });
};

export const getStaticRecruitmentRuntimeKey = (
  authorityGeneration: number,
): string => `recruitment:${authorityGeneration}`;

export const buildStaticRecruitmentRuntime = (
  authorityGeneration: number,
): CompiledRuntime => {
  const resources = Object.freeze(RESOURCE_IDS.map(resource));
  return Object.freeze({
    key: getStaticRecruitmentRuntimeKey(authorityGeneration),
    packKey: "recruitment",
    resources,
    routes: Object.freeze(ROUTE_IDS.map(route)),
    dashboard: dashboard(),
    navigation: Object.freeze(NAVIGATION_IDS.map(navigation)),
    conversationSlots: conversationSlots(),
    availableResources: new Set(resources.map(({ name }) => name)),
  });
};
