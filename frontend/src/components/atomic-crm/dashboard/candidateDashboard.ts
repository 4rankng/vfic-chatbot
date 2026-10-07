import type { Conversation, Lead } from "../types";
import { VIETNAM_TIME_ZONE, vietnamFormatter } from "../vietnamTime";
import { buildRecruitmentContextIdentity } from "../leads/domain/recruitmentPresentation";
import {
  getDashboardCandidates,
  getDashboardConversations,
  getDashboardConversationsByContactIds,
} from "../reporting/reportingService";

export interface DashboardCandidate {
  id: number;
  zalo_id: string | null;
  name: string | null;
  phone: string | null;
  avatar_url: string | null;
  conversation_id: string | null;
  created_at: string;
  lead: Lead;
}

type DashboardCandidateSource = Omit<
  Lead,
  | "zalo_id"
  | "name"
  | "phone"
  | "desired_job"
  | "expected_salary"
  | "lead_score"
  | "lead_stage"
  | "updated_at"
> & {
  zalo_id: string | null;
  name: string | null;
  phone: string | null;
  desired_job?: string | null;
  expected_salary?: string | null;
  lead_score?: Lead["lead_score"];
  lead_stage?: string | null;
  updated_at?: string | null;
};

interface CandidateListEnvelope {
  data: DashboardCandidateSource[];
  total: number;
}

interface ConversationListEnvelope {
  data: Conversation[];
  total: number;
}

export interface CandidateDayGroup {
  key: string;
  label: string;
  candidates: DashboardCandidate[];
}

export const CANDIDATES_QUERY_KEY = [
  "dashboard-candidates-with-phone",
] as const;

// "en" deliberately: `dayKey` reads numeric parts to build a sortable
// YYYY-MM-DD key, and "en" keeps those parts Latin-numeric. The timezone is
// still Vietnam's — only the locale differs from `vietnamFormatter`.
const dayKey = (value: Date): string => {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: VIETNAM_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const part = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
};

const dayLabel = (value: Date, now: Date): string => {
  const key = dayKey(value);
  if (key === dayKey(now)) return "Hôm nay";

  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  if (key === dayKey(yesterday)) return "Hôm qua";

  const label = vietnamFormatter({
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(value);
  return label.charAt(0).toUpperCase() + label.slice(1);
};

const validTimestamp = (value: string): number => {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp;
};

export const groupCandidatesByDay = (
  rows: DashboardCandidate[],
  now = new Date(),
): CandidateDayGroup[] => {
  const sorted = rows
    .filter((candidate) => candidate.phone?.trim())
    .sort(
      (left, right) =>
        validTimestamp(right.created_at) - validTimestamp(left.created_at),
    );
  const groups = new Map<string, CandidateDayGroup>();

  for (const candidate of sorted) {
    const createdAt = new Date(candidate.created_at);
    if (Number.isNaN(createdAt.getTime())) continue;
    const key = dayKey(createdAt);
    const existing = groups.get(key);
    if (existing) {
      existing.candidates.push(candidate);
    } else {
      groups.set(key, {
        key,
        label: dayLabel(createdAt, now),
        candidates: [candidate],
      });
    }
  }

  return Array.from(groups.values());
};

export const fetchDashboardCandidates = async (): Promise<
  DashboardCandidate[]
> => {
  const candidateResponse =
    await getDashboardCandidates<CandidateListEnvelope>();
  const candidates = candidateResponse.data.filter((candidate) =>
    candidate.phone?.trim(),
  );
  const zaloIds = Array.from(
    new Set(
      candidates
        .map((candidate) => candidate.zalo_id)
        .filter((value): value is string => Boolean(value)),
    ),
  );
  // Contact-keyed candidates (Alembic 0047: Messenger rows carry a NULL
  // zalo_id) are invisible to a chat-id lookup, so their conversations are
  // resolved by contact id as well — the dashboard twin of
  // loadRecruitmentConversationRows' dual-key lookup.
  const contactIds = Array.from(
    new Set(
      candidates
        .map((candidate) => candidate.contact_id)
        .filter((value): value is string => Boolean(value)),
    ),
  );
  const [zaloConversationResponse, contactConversationResponse] =
    await Promise.all([
      zaloIds.length > 0
        ? getDashboardConversations<ConversationListEnvelope>(zaloIds)
        : { data: [], total: 0 },
      contactIds.length > 0
        ? getDashboardConversationsByContactIds<ConversationListEnvelope>(
            contactIds,
          )
        : { data: [], total: 0 },
    ]);
  const conversationsByZaloId = new Map<string, Conversation[]>();
  for (const conversation of zaloConversationResponse.data) {
    if (!conversation.zalo_chat_id) continue;
    const rows = conversationsByZaloId.get(conversation.zalo_chat_id) ?? [];
    rows.push(conversation);
    conversationsByZaloId.set(conversation.zalo_chat_id, rows);
  }
  const conversationsByContactId = new Map<string, Conversation[]>();
  for (const conversation of contactConversationResponse.data) {
    if (!conversation.contact_id) continue;
    const rows = conversationsByContactId.get(conversation.contact_id) ?? [];
    rows.push(conversation);
    conversationsByContactId.set(conversation.contact_id, rows);
  }

  return candidates.map((candidate) => {
    // The Zalo chat id is the exact thread key (leads_zalo_id_fkey), so it wins;
    // the contact match only reaches contact-keyed candidates whose chat id is
    // NULL. Both lists arrive newest-activity-first, so [0] is the latest
    // thread as before.
    const conversations =
      (candidate.zalo_id
        ? conversationsByZaloId.get(candidate.zalo_id)
        : undefined) ??
      (candidate.contact_id
        ? conversationsByContactId.get(candidate.contact_id)
        : undefined) ??
      [];
    const conversation = conversations[0];
    const profileConversation = conversations.find(
      (row) =>
        row.zalo_channel === "oa" &&
        Boolean(row.contact?.display_name || row.contact?.avatar_url),
    );
    const profile = profileConversation
      ? buildRecruitmentContextIdentity(profileConversation, {
          name: candidate.name ?? "",
          avatar_url: candidate.avatar_url,
          phone: candidate.phone ?? "",
        })
      : {
          displayName: candidate.name || "Ứng viên mới",
          avatarUrl: candidate.avatar_url,
        };
    return {
      id: candidate.id,
      zalo_id: candidate.zalo_id,
      name: profile.displayName,
      phone: candidate.phone,
      avatar_url: profile.avatarUrl ?? null,
      conversation_id: conversation?.id ?? null,
      created_at: candidate.created_at,
      lead: {
        ...candidate,
        zalo_id: candidate.zalo_id ?? "",
        name: candidate.name ?? "",
        phone: candidate.phone ?? "",
        desired_job: candidate.desired_job ?? "",
        expected_salary: candidate.expected_salary ?? "",
        lead_score: candidate.lead_score ?? null,
        lead_stage: candidate.lead_stage ?? "",
        updated_at: candidate.updated_at ?? candidate.created_at,
        avatar_url: profile.avatarUrl ?? null,
      },
    };
  });
};
