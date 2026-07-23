import { getDashboardCandidates } from "../reporting/reportingService";

export interface DashboardCandidate {
  id: number;
  name: string | null;
  phone: string | null;
  desired_job: string | null;
  created_at: string;
}

interface CandidateListEnvelope {
  data: DashboardCandidate[];
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
  const response = await getDashboardCandidates<CandidateListEnvelope>();
  return response.data.filter((candidate) => candidate.phone?.trim());
};
