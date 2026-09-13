import type { Conversation, Lead } from "../../types";

type RecruitmentProfileSource = Pick<
  Conversation,
  "zalo_channel" | "zalo_chat_id" | "contact" | "channel_identity"
>;

export type RecruitmentRowPresentation = {
  displayName: string;
  subtitle: string;
  avatarUrl?: string | null;
  searchText: string;
  channelProfileName?: string;
};

export type RecruitmentContextIdentity = {
  displayName: string;
  avatarUrl?: string;
  secondaryName?: string;
  phone?: string;
};

// Zalo Bot Platform exposes no real profile, so an unconfirmed candidate stays
// anonymous there. Every other channel — Zalo OA, Messenger — carries a genuine
// profile name worth showing. `zalo_channel` only discriminates Zalo rows: a
// Messenger conversation keeps the "bot" default, so the neutral provider
// decides whenever the channel identity is known.
const usesChannelProfile = (
  conversation: RecruitmentProfileSource,
): boolean => {
  const provider = conversation.channel_identity?.provider;
  if (provider) return provider !== "zalo_bot";
  return conversation.zalo_channel === "oa";
};

const resolveChannelProfileName = (
  conversation: RecruitmentProfileSource,
): string | undefined =>
  usesChannelProfile(conversation)
    ? conversation.contact?.display_name?.trim() || undefined
    : undefined;

// Messenger rows carry no zalo_chat_id, so the neutral external id is what is
// left to identify an unnamed candidate by.
const fallbackCandidateName = (conversation: RecruitmentProfileSource) =>
  `Ứng viên · ${(conversation.zalo_chat_id || conversation.channel_identity?.external_id || "").slice(-4)}`;

const normalizeSearchText = (parts: Array<string | null | undefined>) =>
  parts.filter((part): part is string => Boolean(part?.trim())).join(" ");

export const resolveRecruitmentProfile = (
  conversation: RecruitmentProfileSource,
  lead: Pick<Lead, "name" | "avatar_url"> | undefined,
) => {
  const channelProfileName = resolveChannelProfileName(conversation);

  return {
    displayName:
      lead?.name || channelProfileName || fallbackCandidateName(conversation),
    // Same fallback chain as the thread header: the channel profile photo
    // serves every channel, the lead record's avatar is only the first pick.
    avatarUrl:
      lead?.avatar_url || conversation.contact?.avatar_url || undefined,
    channelProfileName,
  };
};

export const buildRecruitmentRowPresentation = (
  conversation: RecruitmentProfileSource,
  lead: Lead | undefined,
): RecruitmentRowPresentation => {
  const profile = resolveRecruitmentProfile(conversation, lead);
  return {
    displayName: profile.displayName,
    subtitle: lead?.phone || "",
    avatarUrl: profile.avatarUrl,
    channelProfileName: profile.channelProfileName,
    searchText: normalizeSearchText([
      conversation.zalo_chat_id,
      lead?.name,
      profile.channelProfileName,
      lead?.phone,
      lead?.desired_job,
      lead?.region,
      lead?.living_area,
    ]),
  };
};

export const buildRecruitmentContextIdentity = (
  conversation: RecruitmentProfileSource,
  lead: Pick<Lead, "name" | "avatar_url" | "phone"> | undefined,
): RecruitmentContextIdentity => {
  const profileName = resolveChannelProfileName(conversation);
  const leadName = lead?.name?.trim();
  const displayName =
    profileName || leadName || fallbackCandidateName(conversation);
  const avatarUrl = profileName
    ? (conversation.contact?.avatar_url ?? lead?.avatar_url ?? undefined)
    : (lead?.avatar_url ?? conversation.contact?.avatar_url ?? undefined);
  return {
    displayName,
    avatarUrl,
    secondaryName: leadName && leadName !== displayName ? leadName : undefined,
    phone: lead?.phone?.trim() || undefined,
  };
};

export const shouldRefreshLeadIdentity = (
  currentLeadId: string | number | null | undefined,
  currentZaloId: string | null | undefined,
  payload: {
    id?: string | number;
    lead_id?: string | number;
    zalo_id?: string | null;
  },
) => {
  const payloadLeadId = payload.lead_id ?? payload.id;
  const sameLead =
    payloadLeadId != null &&
    currentLeadId != null &&
    String(payloadLeadId) === String(currentLeadId);
  const sameZalo =
    Boolean(payload.zalo_id) && payload.zalo_id === currentZaloId;
  return sameLead || sameZalo;
};
