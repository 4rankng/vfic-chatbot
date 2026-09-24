import { Dashboard } from "../../dashboard/Dashboard";
import {
  getLeadPriorityChip,
  getLeadStatusColor,
} from "../../conversations/domain/conversation-display";
import type { Conversation } from "../../types";
import { loadRecruitmentConversationRows } from "../../leads/application/loadRecruitmentConversationRows";
import { leadDirectoryApi } from "../../leads/infrastructure/leadDirectoryApi";
import type {
  ConversationFilterSlot,
  ConversationRowPresentation,
  ConversationRowSlot,
  ExecutableCapabilityModule,
} from "../types";
import {
  RecruitmentConversationActions,
  RecruitmentConversationContext,
} from "./components";

export { resolveRecruitmentProfile } from "../../leads/domain/recruitmentPresentation";

const loadRecruitmentRows: ConversationRowSlot["load"] = async (
  conversations,
  signal,
) => {
  const rows = await loadRecruitmentConversationRows(
    conversations as Conversation[],
    leadDirectoryApi,
    {
      get aborted() {
        return signal.aborted;
      },
      onAbort: (listener) => {
        signal.addEventListener("abort", listener, { once: true });
        return () => signal.removeEventListener("abort", listener);
      },
    },
  );
  const presentations = new Map<string, ConversationRowPresentation>();
  for (const conversation of conversations) {
    const row = rows.get(conversation.id);
    const lead = row?.lead;
    const colors = getLeadStatusColor(lead);
    const priority = getLeadPriorityChip(lead);
    presentations.set(conversation.id, {
      displayName: row?.presentation.displayName ?? "",
      subtitle: row?.presentation.subtitle ?? "",
      avatarUrl: row?.presentation.avatarUrl,
      avatarBackground: colors.bg,
      avatarForeground: colors.ink,
      searchText: row?.presentation.searchText ?? "",
      priorityTone:
        lead?.lead_score === "hot" || lead?.lead_score === "warm"
          ? lead.lead_score
          : undefined,
      priorityLabel: priority?.label,
    });
  }
  return presentations;
};

const rowSlot: ConversationRowSlot = Object.freeze({
  load: loadRecruitmentRows,
});
const filterSlot: ConversationFilterSlot = Object.freeze({
  priorityLabel: "Ứng viên ưu tiên",
  matchesPriority: (presentation) => Boolean(presentation.priorityTone),
});

export const contributions: ExecutableCapabilityModule["contributions"] = {
  "recruitment.dashboard.attention": {
    kind: "dashboard",
    dashboard: Dashboard,
  },
  "recruitment.conversation.row": {
    kind: "conversation-slot",
    slot: "row",
    value: rowSlot,
  },
  "recruitment.conversation.filters": {
    kind: "conversation-slot",
    slot: "filters",
    value: filterSlot,
  },
  "recruitment.conversation.context": {
    kind: "conversation-slot",
    slot: "context",
    value: RecruitmentConversationContext,
  },
  "recruitment.conversation.actions": {
    kind: "conversation-slot",
    slot: "actions",
    value: RecruitmentConversationActions,
  },
};
