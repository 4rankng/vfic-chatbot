import type { QueryClient } from "@tanstack/react-query";
import type {
  DashboardComponent,
  ResourceProps,
  Store,
} from "ra-core";
import type {
  ComponentType,
  ReactNode,
} from "react";
import type { LucideIcon } from "lucide-react";

import type { PublicRuntimeManifest } from "../installation/runtime-manifest";
import type { Conversation } from "../types";

export type ContributionKind =
  | "resource"
  | "route"
  | "dashboard"
  | "navigation"
  | "conversation-slot";

export type ConversationSlotName = "row" | "filters" | "context" | "actions";

export type ContributionContract = Readonly<{
  id: string;
  kind: ContributionKind;
  moduleId: string;
  resourceName?: string;
  routePath?: string;
  routeLayout?: "layout" | "no-layout";
  navigationPath?: string;
  dashboardOwner?: string;
  conversationSlot?: ConversationSlotName;
}>;

export type CapabilityContract = Readonly<{
  id: string;
  dependencies: readonly string[];
  contributionIds: readonly string[];
}>;

export type PackContract = Readonly<{
  key: string;
  version: string;
  kernelAbi: "1";
  contractHash: string;
  parityChecksum: string;
  capabilityIds: readonly string[];
  baseContributionIds: readonly string[];
  contributionOrder?: readonly string[];
  supportedLocales: readonly string[];
  terminologyKeys: readonly string[];
}>;

export type RuntimeModuleLoader = () => Promise<ExecutableCapabilityModule>;

export type FrontendCapabilityRegistry = Readonly<{
  kernelAbi: "1";
  packs: Readonly<Record<string, PackContract>>;
  capabilities: Readonly<Record<string, CapabilityContract>>;
  contributions: Readonly<Record<string, ContributionContract>>;
  moduleLoaders: Readonly<Record<string, RuntimeModuleLoader>>;
}>;

export type ConversationRowPresentation = Readonly<{
  displayName: string;
  subtitle: string;
  avatarUrl?: string | null;
  avatarBackground?: string;
  avatarForeground?: string;
  searchText: string;
  priorityTone?: "hot" | "warm";
  priorityLabel?: string;
}>;

export type ConversationRowSlot = Readonly<{
  load: (
    conversations: readonly Conversation[],
    signal: AbortSignal,
  ) => Promise<ReadonlyMap<string, ConversationRowPresentation>>;
}>;

export type ConversationFilterSlot = Readonly<{
  priorityLabel: string;
  matchesPriority: (presentation: ConversationRowPresentation) => boolean;
}>;

export type ConversationContextValue = Readonly<{
  displayName: string;
  avatarUrl?: string | null;
  avatarBackground?: string;
  avatarForeground?: string;
  externalIdentityLabel?: string;
  avatarAlt: string;
  panelLabel: string;
  renderPanel?: (props: {
    open: boolean;
    persistent: boolean;
    onClose: () => void;
    onCloseAutoFocus: (event: Event) => void;
  }) => ReactNode;
}>;

export type ConversationContextAdapterProps = Readonly<{
  conversation: Conversation | undefined;
  children: (value: ConversationContextValue) => ReactNode;
}>;

export type ConversationContextSlot = ComponentType<ConversationContextAdapterProps>;

export type ConversationActionsSlot = ComponentType<{
  conversation: Conversation | undefined;
}>;

export type ConversationSlots = Readonly<{
  row?: ConversationRowSlot;
  filters?: ConversationFilterSlot;
  context?: ConversationContextSlot;
  actions?: ConversationActionsSlot;
}>;

export type CompiledResource = Readonly<{
  id: string;
  name: string;
  props: Omit<ResourceProps, "name">;
}>;

export type CompiledRoute = Readonly<{
  id: string;
  path: string;
  layout: "layout" | "no-layout";
  Component: ComponentType;
}>;

export type CompiledDestination = Readonly<{
  id: string;
  label: string;
  to: string;
  Icon: LucideIcon;
  roles?: readonly ("admin" | "recruiter")[];
  rail: boolean;
  mobile: boolean;
  isActive: (normalizedPath: string) => boolean;
}>;

export type ExecutableContribution =
  | Readonly<{ kind: "resource"; resource: CompiledResource }>
  | Readonly<{ kind: "route"; route: CompiledRoute }>
  | Readonly<{ kind: "dashboard"; dashboard: DashboardComponent }>
  | Readonly<{ kind: "navigation"; destination: CompiledDestination }>
  | Readonly<{
      kind: "conversation-slot";
      slot: ConversationSlotName;
      value:
        | ConversationRowSlot
        | ConversationFilterSlot
        | ConversationContextSlot
        | ConversationActionsSlot;
    }>;

export type ExecutableCapabilityModule = Readonly<{
  contributions: Readonly<Record<string, ExecutableContribution>>;
}>;

export type CompiledRuntimePlan = Readonly<{
  key: string;
  manifest: PublicRuntimeManifest;
  registry: FrontendCapabilityRegistry;
  contributionIds: readonly string[];
  availableResources: ReadonlySet<string>;
}>;

export type CompiledRuntime = Readonly<{
  key: string;
  packKey: string;
  resources: readonly CompiledResource[];
  routes: readonly CompiledRoute[];
  dashboard: DashboardComponent;
  navigation: readonly CompiledDestination[];
  conversationSlots: ConversationSlots;
  availableResources: ReadonlySet<string>;
}>;

export type RuntimeGenerationBundle = Readonly<{
  key: string;
  runtime: CompiledRuntime;
  queryClient: QueryClient;
  store: Store;
}>;
