import { useEffect, useMemo } from "react";
import { useGetList } from "ra-core";

import { getRealtimeSocket } from "@/lib/vfic/realtimeSocket";
import { apiJson } from "../../providers/rest/api";
import { Dashboard } from "../../dashboard/Dashboard";
import { ConversationContextPanel } from "../../conversations/ConversationContextPanel";
import {
  getLeadPriorityChip,
  getLeadStatusColor,
} from "../../conversations/conversationDisplay";
import type { Conversation, Lead } from "../../types";
import type {
  ConversationActionsSlot,
  ConversationContextAdapterProps,
  ConversationFilterSlot,
  ConversationRowPresentation,
  ConversationRowSlot,
  ExecutableCapabilityModule,
} from "../types";

type ListEnvelope = { data: Record<string, unknown>[]; total: number };

type RecruitmentProfileSource = Pick<
  Conversation,
  "zalo_channel" | "zalo_chat_id" | "contact"
>;

export const resolveRecruitmentProfile = (
  conversation: RecruitmentProfileSource,
  lead: Pick<Lead, "name" | "avatar_url"> | undefined,
) => {
  const oaProfileName =
    conversation.zalo_channel === "oa"
      ? conversation.contact?.display_name?.trim()
      : undefined;
  const oaProfileAvatar =
    conversation.zalo_channel === "oa"
      ? conversation.contact?.avatar_url
      : undefined;
  return {
    displayName:
      lead?.name ||
      oaProfileName ||
      `Ứng viên · ${(conversation.zalo_chat_id || "").slice(-4)}`,
    avatarUrl: lead?.avatar_url || oaProfileAvatar,
    oaProfileName,
  };
};

const loadRecruitmentRows: ConversationRowSlot["load"] = async (
  conversations,
  signal,
) => {
  const zaloIds = Array.from(
    new Set(conversations.map((conversation) => conversation.zalo_chat_id).filter(Boolean)),
  );
  if (zaloIds.length === 0) return new Map();
  const search = new URLSearchParams({
    zalo_ids: zaloIds.join(","),
    per_page: String(zaloIds.length),
  });
  const body = await apiJson<ListEnvelope>(`/api/v1/leads?${search.toString()}`, {
    signal,
  });
  const leads = body.data as unknown as Lead[];
  const leadByZalo = new Map<string, Lead>();
  for (const lead of leads) {
    if (lead.zalo_id && !leadByZalo.has(lead.zalo_id)) {
      leadByZalo.set(lead.zalo_id, lead);
    }
  }
  const presentations = new Map<string, ConversationRowPresentation>();
  for (const conversation of conversations) {
    const chatKey = conversation.zalo_chat_id ?? conversation.id;
    const lead = leadByZalo.get(chatKey);
    const { displayName, avatarUrl, oaProfileName } = resolveRecruitmentProfile(
      conversation,
      lead,
    );
    const colors = getLeadStatusColor(lead);
    const priority = getLeadPriorityChip(lead);
    presentations.set(conversation.id, {
      displayName,
      subtitle: lead?.phone || "",
      avatarUrl,
      avatarBackground: colors.bg,
      avatarForeground: colors.ink,
      searchText: [
        conversation.zalo_chat_id,
        lead?.name,
        oaProfileName,
        lead?.phone,
        lead?.desired_job,
        lead?.region,
        lead?.living_area,
      ]
        .filter(Boolean)
        .join(" "),
      priorityTone:
        lead?.lead_score === "hot" || lead?.lead_score === "warm"
          ? lead.lead_score
          : undefined,
      priorityLabel: priority?.label,
    });
  }
  return presentations;
};

const rowSlot: ConversationRowSlot = Object.freeze({ load: loadRecruitmentRows });
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

  useEffect(() => {
    if (!lead?.id) return;
    const leadId = String(lead.id);
    const socket = getRealtimeSocket();
    const handleLeadUpdated = (payload: {
      id?: string | number;
      lead_id?: string | number;
      zalo_id?: string | null;
    }) => {
      const payloadLeadId = payload.lead_id ?? payload.id;
      const sameLead = payloadLeadId != null && String(payloadLeadId) === leadId;
      const sameZalo =
        Boolean(payload.zalo_id) && payload.zalo_id === conversation?.zalo_chat_id;
      if (sameLead || sameZalo) void refetch();
    };
    socket.on("lead.updated", handleLeadUpdated);
    if (!socket.connected) socket.connect();
    socket.emit("join lead", { lead_id: lead.id });
    return () => {
      socket.off("lead.updated", handleLeadUpdated);
      socket.emit("leave lead", { lead_id: lead.id });
    };
  }, [conversation?.zalo_chat_id, lead?.id, refetch]);

  // Header identity is profile-name-first: the channel/OA display name leads
  // (it is what the candidate sees as their own identity), with the recruiter-
  // confirmed real name demoted to the subtitle only when it differs — i.e. the
  // profile name is a nickname. The conversation LIST keeps the inverse priority
  // (lead name first) via resolveRecruitmentProfile, since recruiters scanning
  // the directory want the confirmed name; the two views need not match.
  const source =
    conversation ?? { zalo_channel: "bot" as const, zalo_chat_id: null, contact: null };
  const profileName =
    source.zalo_channel === "oa"
      ? source.contact?.display_name?.trim()
      : undefined;
  const leadName = lead?.name?.trim();
  const fallbackName = `Ứng viên · ${(source.zalo_chat_id || "").slice(-4)}`;
  const displayName = profileName || leadName || fallbackName;
  const avatarUrl = profileName
    ? (source.contact?.avatar_url ?? lead?.avatar_url ?? undefined)
    : (lead?.avatar_url ?? source.contact?.avatar_url ?? undefined);
  const secondaryName =
    leadName && leadName !== displayName ? leadName : undefined;
  const phone = lead?.phone?.trim() || undefined;
  const colors = getLeadStatusColor(lead);
  return (
    <>
      {children({
        displayName,
        avatarUrl,
        avatarBackground: colors.bg,
        avatarForeground: colors.ink,
        contactSubtitle:
          secondaryName || phone ? { secondaryName, phone } : undefined,
        avatarAlt: `Ảnh đại diện của ${displayName}`,
        panelLabel: "thông tin ứng viên",
        renderPanel: ({ open, persistent, onClose, onCloseAutoFocus }) => (
          <ConversationContextPanel
            lead={lead}
            open={open}
            persistent={persistent}
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
