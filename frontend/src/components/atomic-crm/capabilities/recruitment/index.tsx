import { useEffect, useMemo } from "react";
import { useDataProvider, useGetList, useNotify } from "ra-core";

import {
  getRealtimeSocket,
  type RealtimeSocket,
} from "../../providers/realtime/realtime-socket";
import { Dashboard } from "../../dashboard/Dashboard";
import { ConversationContextPanel } from "../../conversations/ConversationContextPanel";
import type { CandidateProfileUpdate } from "../../leads/domain/candidateProfile";
import { useRoleActions } from "../../hooks/useRoleActions";
import {
  getLeadPriorityChip,
  getLeadStatusColor,
} from "../../conversations/domain/conversation-display";
import type { Conversation, Lead } from "../../types";
import { loadRecruitmentConversationRows } from "../../leads/application/loadRecruitmentConversationRows";
import {
  buildRecruitmentContextIdentity,
  shouldRefreshLeadIdentity,
} from "../../leads/domain/recruitmentPresentation";
import { leadDirectoryApi } from "../../leads/infrastructure/leadDirectoryApi";
import type { LeadRealtimePort } from "../../leads/application/ports";
import { createLeadRealtimePort } from "../../leads/infrastructure/leadRealtime";
import type { CrmDataProvider } from "../../providers/types";
import type {
  ConversationActionsSlot,
  ConversationContextAdapterProps,
  ConversationFilterSlot,
  ConversationRowPresentation,
  ConversationRowSlot,
  ExecutableCapabilityModule,
} from "../types";
export { resolveRecruitmentProfile } from "../../leads/domain/recruitmentPresentation";

// Built on demand, never at import time: this module sits in the eager entry
// graph, and creating the port would construct the socket.io Manager (and pull
// socket.io-client onto first paint) before any conversation is opened. The
// cache is keyed on the socket instance because logout drops the singleton —
// a port that kept the old socket would emit into a closed connection.
let cachedLeadRealtimePort: {
  socket: RealtimeSocket;
  port: LeadRealtimePort;
} | null = null;

const getLeadRealtimePort = (): LeadRealtimePort => {
  const socket = getRealtimeSocket();
  if (cachedLeadRealtimePort?.socket !== socket) {
    cachedLeadRealtimePort = { socket, port: createLeadRealtimePort(socket) };
  }
  return cachedLeadRealtimePort.port;
};

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

const RecruitmentConversationContext = ({
  conversation,
  children,
}: ConversationContextAdapterProps) => {
  const params = useMemo(
    () => ({
      filter: { zalo_id: conversation?.zalo_chat_id },
      pagination: { page: 1, perPage: 1 },
    }),
    [conversation?.zalo_chat_id],
  );
  const options = useMemo(
    () => ({ enabled: Boolean(conversation?.zalo_chat_id) }),
    [conversation?.zalo_chat_id],
  );
  const { data, refetch } = useGetList("leads", params, options);
  const lead = data?.[0] as Lead | undefined;
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const { canEdit } = useRoleActions();

  useEffect(() => {
    if (!lead?.id) return;
    return getLeadRealtimePort().subscribeToLeadUpdates(lead.id, (payload) => {
      if (
        shouldRefreshLeadIdentity(lead.id, conversation?.zalo_chat_id, payload)
      ) {
        void refetch();
      }
    });
  }, [conversation?.zalo_chat_id, lead?.id, refetch]);

  // Header identity is profile-name-first: the channel/OA display name leads
  // (it is what the candidate sees as their own identity), with the recruiter-
  // confirmed real name demoted to the subtitle only when it differs — i.e. the
  // profile name is a nickname. The conversation LIST keeps the inverse priority
  // (lead name first) via resolveRecruitmentProfile, since recruiters scanning
  // the directory want the confirmed name; the two views need not match.
  const source = conversation ?? {
    zalo_channel: "bot" as const,
    zalo_chat_id: null,
    contact: null,
  };
  const identity = buildRecruitmentContextIdentity(source, lead);
  const colors = getLeadStatusColor(lead);
  const saveCandidateProfile = async (
    changes: Partial<CandidateProfileUpdate>,
    version: number,
  ) => {
    if (!lead) return;
    try {
      await dataProvider.update<Lead>("leads", {
        id: lead.id,
        data: { ...changes, version },
        previousData: lead,
      });
      notify("Đã cập nhật hồ sơ ứng viên", { type: "success" });
      await refetch().catch(() => undefined);
    } catch (error) {
      await refetch().catch(() => undefined);
      notify(
        error instanceof Error
          ? error.message
          : "Không thể cập nhật hồ sơ ứng viên",
        { type: "error" },
      );
      throw error;
    }
  };
  return (
    <>
      {children({
        displayName: identity.displayName,
        avatarUrl: identity.avatarUrl,
        avatarBackground: colors.bg,
        avatarForeground: colors.ink,
        contactSubtitle:
          identity.secondaryName || identity.phone
            ? {
                secondaryName: identity.secondaryName,
                phone: identity.phone,
              }
            : undefined,
        avatarAlt: `Ảnh đại diện của ${identity.displayName}`,
        panelLabel: "Dữ Liệu Ứng Viên",
        renderPanel: ({ open, persistent, onClose, onCloseAutoFocus }) => (
          <ConversationContextPanel
            lead={lead}
            open={open}
            persistent={persistent}
            canEdit={canEdit}
            onSave={saveCandidateProfile}
            onClose={onClose}
            onCloseAutoFocus={onCloseAutoFocus}
          />
        ),
      })}
    </>
  );
};

const RecruitmentConversationActions: ConversationActionsSlot = () => null;

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
