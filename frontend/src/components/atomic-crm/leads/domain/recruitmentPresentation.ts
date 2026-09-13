import type { Conversation, Lead } from "../../types";

type RecruitmentProfileSource = Pick<
  Conversation,
  "zalo_channel" | "zalo_chat_id" | "contact"
>;

export type RecruitmentRowPresentation = {
  displayName: string;
  subtitle: string;
  avatarUrl?: string | null;
  searchText: string;
  oaProfileName?: string;
};

export type RecruitmentContextIdentity = {
  displayName: string;
  avatarUrl?: string;
  secondaryName?: string;
  phone?: string;
};

const fallbackCandidateName = (zaloChatId: string | null | undefined) =>
  `Ứng viên · ${(zaloChatId || "").slice(-4)}`;

const normalizeSearchText = (parts: Array<string | null | undefined>) =>
  parts.filter((part): part is string => Boolean(part?.trim())).join(" ");

export const resolveRecruitmentProfile = (
  conversation: RecruitmentProfileSource,
  lead: Pick<Lead, "name" | "avatar_url"> | undefined,
) => {
  const oaProfileName =
    conversation.zalo_channel === "oa"
      ? conversation.contact?.display_name?.trim()
      : undefined;

  return {
    displayName:
      lead?.name ||
      oaProfileName ||
      fallbackCandidateName(conversation.zalo_chat_id),
    // Same fallback chain as the thread header: the channel profile photo
    // serves every channel, the lead record's avatar is only the first pick.
    avatarUrl:
      lead?.avatar_url || conversation.contact?.avatar_url || undefined,
    oaProfileName,
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
    oaProfileName: profile.oaProfileName,
    searchText: normalizeSearchText([
      conversation.zalo_chat_id,
      lead?.name,
      profile.oaProfileName,
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
  const profileName =
    conversation.zalo_channel === "oa"
      ? conversation.contact?.display_name?.trim()
      : undefined;
  const leadName = lead?.name?.trim();
  const displayName =
    profileName || leadName || fallbackCandidateName(conversation.zalo_chat_id);
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
