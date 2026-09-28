import { useEffect, useMemo } from "react";
import { useDataProvider, useGetList, useNotify } from "ra-core";

import {
  getRealtimeSocket,
  type RealtimeSocket,
} from "../../providers/realtime/realtime-socket";
import { ConversationContextPanel } from "../../conversations/ConversationContextPanel";
import type { CandidateProfileUpdate } from "../../leads/domain/candidateProfile";
import { useRoleActions } from "../../hooks/useRoleActions";
import { getLeadStatusColor } from "../../conversations/domain/conversation-display";
import type { Lead } from "../../types";
import { leadFilterFor } from "../../leads/domain/leadLookupKey";
import {
  buildRecruitmentContextIdentity,
  shouldRefreshLeadIdentity,
} from "../../leads/domain/recruitmentPresentation";
import type { LeadRealtimePort } from "../../leads/application/ports";
import { createLeadRealtimePort } from "../../leads/infrastructure/leadRealtime";
import type { CrmDataProvider } from "../../providers/types";
import type {
  ConversationActionsSlot,
  ConversationContextAdapterProps,
} from "../types";

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

export const RecruitmentConversationContext = ({
  conversation,
  children,
}: ConversationContextAdapterProps) => {
  const zaloChatId = conversation?.zalo_chat_id ?? null;
  const contactId = conversation?.contact_id ?? null;
  const params = useMemo(
    () => ({
      filter: leadFilterFor(zaloChatId, contactId),
      pagination: { page: 1, perPage: 1 },
    }),
    [zaloChatId, contactId],
  );
  const options = useMemo(
    () => ({
      enabled: Boolean(zaloChatId || contactId),
    }),
    [zaloChatId, contactId],
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
  // Save handlers report their own outcome, so a rejected refresh is awaited
  // and dropped here rather than surfacing as a save failure.
  const refetchQuietly = async (): Promise<void> => {
    try {
      await refetch();
    } catch {
      // Swallowed on purpose: the caller reports the save result.
    }
  };
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
      await refetchQuietly();
    } catch (error) {
      await refetchQuietly();
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

export const RecruitmentConversationActions: ConversationActionsSlot = () =>
  null;
