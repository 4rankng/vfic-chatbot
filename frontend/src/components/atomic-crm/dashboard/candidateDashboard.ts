import type { Conversation } from "../types";
import { buildRecruitmentContextIdentity } from "../leads/domain/recruitmentPresentation";
import {
  getDashboardCandidates,
  getDashboardConversations,
} from "../reporting/reportingService";

export interface DashboardCandidate {
  id: number;
  zalo_id: string | null;
  name: string | null;
  phone: string | null;
  avatar_url: string | null;
  conversation_id: string | null;
  created_at: string;
}

type DashboardCandidateSource = Omit<
  DashboardCandidate,
  "conversation_id"
> & {
  desired_job?: string | null;
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

const VIETNAM_TIME_ZONE = "Asia/Ho_Chi_Minh";

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

  const label = new Intl.DateTimeFormat("vi-VN", {
    timeZone: VIETNAM_TIME_ZONE,
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
  const conversationResponse =
    zaloIds.length > 0
      ? await getDashboardConversations<ConversationListEnvelope>(zaloIds)
      : { data: [], total: 0 };
  const conversationsByZaloId = new Map<string, Conversation[]>();
  for (const conversation of conversationResponse.data) {
    if (!conversation.zalo_chat_id) continue;
    const rows = conversationsByZaloId.get(conversation.zalo_chat_id) ?? [];
    rows.push(conversation);
    conversationsByZaloId.set(conversation.zalo_chat_id, rows);
  }

  return candidates
    .map((candidate) => {
      const conversations = candidate.zalo_id
        ? conversationsByZaloId.get(candidate.zalo_id) ?? []
        : [];
      const conversation = conversations[0];
      const profileConversation =
        conversations.find(
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
      };
    });
};
