import type { QueryClient } from "@tanstack/react-query";
import type { DashboardComponent, ResourceProps, Store } from "ra-core";
import type { ComponentType, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import type { Conversation } from "../types";

export type ConversationSlotName = "row" | "filters" | "context" | "actions";

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
  /** Muted descriptor shown beneath the header name. `secondaryName` is the
   * recruiter-confirmed real name, surfaced only when it differs from the
   * profile display name (i.e. the profile name is a nickname). `phone` is the
   * candidate mobile number when captured. The context panel remains the
   * detailed source. */
  contactSubtitle?: Readonly<{ secondaryName?: string; phone?: string }>;
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

export type ConversationContextSlot =
  ComponentType<ConversationContextAdapterProps>;

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

/**
 * Sidebar section a destination belongs to. The sidebar groups destinations by
 * this id and the layout owns the section headings, so the compiled contract
 * carries identity rather than presentation.
 */
export type DestinationSection = "operations" | "knowledge" | "team" | "system";

export type CompiledDestination = Readonly<{
  id: string;
  label: string;
  to: string;
  Icon: LucideIcon;
  roles?: readonly ("admin" | "recruiter")[];
  section: DestinationSection;
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
