import {
  ADAPTER_PROVIDERS,
  type AdapterPersonaAssignment,
  type AdapterProvider,
  type Persona,
} from "../../types";

export type RowFeedback = {
  pending: boolean;
  success: string | null;
  error: string | null;
};

export const EMPTY_ROW_FEEDBACK: RowFeedback = {
  pending: false,
  success: null,
  error: null,
};

export const ADAPTER_LABELS: Record<AdapterProvider, string> = {
  zalo_bot: "Zalo Chatbot",
  zalo_oa: "Zalo OA",
  facebook_messenger: "Messenger",
};

export const createInitialAssignmentFeedback = (): Record<
  AdapterProvider,
  RowFeedback
> => ({
  zalo_bot: { ...EMPTY_ROW_FEEDBACK },
  zalo_oa: { ...EMPTY_ROW_FEEDBACK },
  facebook_messenger: { ...EMPTY_ROW_FEEDBACK },
});

export const normalizePersonaAssignments = (
  assignments: AdapterPersonaAssignment[],
): AdapterPersonaAssignment[] =>
  ADAPTER_PROVIDERS.map((provider) => {
    const existing = assignments.find((item) => item.provider === provider);
    return (
      existing ?? {
        provider,
        label: ADAPTER_LABELS[provider],
        persona_id: null,
        effective_persona_id: null,
        is_default: false,
      }
    );
  });

export const getPersonaAssignmentState = (
  assignment: AdapterPersonaAssignment,
  persona: Persona,
) => {
  if (assignment.persona_id === persona.id) {
    return {
      badge: "Gán riêng",
      badgeVariant: "brand" as const,
      summary: "Adapter này đang gán rõ ràng Agent này.",
      actionLabel: "Trả về mặc định",
      nextPersonaId: null as string | null,
      actionDisabled: false,
    };
  }

  if (assignment.is_default && assignment.effective_persona_id === persona.id) {
    return {
      badge: "Theo mặc định",
      badgeVariant: "good" as const,
      summary: "Adapter này đang kế thừa Agent này từ mặc định toàn hệ thống.",
      actionLabel: "Agent mặc định",
      nextPersonaId: null as string | null,
      actionDisabled: true,
    };
  }

  return {
    badge: assignment.persona_id ? "Agent khác" : "Mặc định khác",
    badgeVariant: "neutral" as const,
    summary: assignment.persona_id
      ? "Adapter này đang gán rõ ràng một Agent khác."
      : "Adapter này đang kế thừa một Agent mặc định khác.",
    actionLabel: "Gán Agent này",
    nextPersonaId: persona.id,
    actionDisabled: false,
  };
};
