import { LEAD_STAGES, type LeadStageValue } from "../types";
import { vietnameseSearchIncludes } from "@/lib/vietnameseSearch";

/**
 * Phone (<640px) leads card-directory: pure filter/sort/chip composition over
 * the dashboard's fetched lead rows. The desktop keeps its day-grouped row
 * list; this module exists so the card list, the stage chips and the sort
 * control share one tested selection policy.
 */

export type LeadSortMode = "newest" | "oldest" | "name";
export type LeadStageFilter = "all" | LeadStageValue;

/** One row of the card directory (dashboard candidate with its lead). */
export type LeadCardRow = {
  id: number;
  name: string | null;
  phone: string | null;
  desired_job: string | null;
  expected_salary: string | null;
  lead_stage: string | null;
  conversation_id: string | null;
  created_at: string;
};

export type LeadCardQuery = {
  query: string;
  stage: LeadStageFilter;
  sort: LeadSortMode;
};

export const LEAD_SORT_LABELS: Record<LeadSortMode, string> = {
  newest: "Mới nhất",
  oldest: "Cũ nhất",
  name: "Tên A–Z",
};

export const LEAD_STAGE_FILTERS: readonly {
  value: LeadStageFilter;
  label: string;
}[] = [
  { value: "all", label: "Tất cả" },
  ...LEAD_STAGES.map((stage) => ({ value: stage.value, label: stage.label })),
];

/** Stable badge class per stage (palette lives in dashboard.css). */
export const LEAD_STAGE_BADGE_CLASS: Record<LeadStageValue, string> = {
  NEW: "lead-card-badge--new",
  CONTACTING: "lead-card-badge--contacting",
  REGISTERED: "lead-card-badge--registered",
  SKIPPED: "lead-card-badge--skipped",
};

export type LeadStageMeta = {
  label: string;
  badgeClass: string;
};

/**
 * How one lead stage renders on a card. Unknown/absent stages (partially
 * populated rows) fall back to the neutral badge instead of throwing.
 */
export const leadStageMeta = (stage: string | null): LeadStageMeta => {
  const known = stage
    ? LEAD_STAGES.find((entry) => entry.value === stage)
    : undefined;
  return {
    label: known?.label ?? "Chưa có giai đoạn",
    badgeClass: known
      ? LEAD_STAGE_BADGE_CLASS[known.value]
      : "lead-card-badge--unknown",
  };
};

const STAGE_FILTER_MATCHERS: Record<
  LeadStageFilter,
  (row: LeadCardRow) => boolean
> = {
  all: () => true,
  NEW: (row) => row.lead_stage === "NEW",
  CONTACTING: (row) => row.lead_stage === "CONTACTING",
  REGISTERED: (row) => row.lead_stage === "REGISTERED",
  SKIPPED: (row) => row.lead_stage === "SKIPPED",
};

const SORT_COMPARATORS: Record<
  LeadSortMode,
  (a: LeadCardRow, b: LeadCardRow) => number
> = {
  newest: (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  oldest: (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
  name: (a, b) =>
    (a.name ?? "").localeCompare(b.name ?? "", "vi", { sensitivity: "base" }),
};

export const filterLeadCardRows = (
  rows: readonly LeadCardRow[],
  { query, stage, sort }: LeadCardQuery,
): LeadCardRow[] => {
  const matchesStage = STAGE_FILTER_MATCHERS[stage];
  const search = query.trim();
  const filtered = rows.filter((row) => {
    if (!matchesStage(row)) return false;
    if (!search) return true;
    const haystack = [row.name, row.phone, row.desired_job]
      .filter(Boolean)
      .join(" ");
    return vietnameseSearchIncludes(haystack, search);
  });
  return filtered.sort(SORT_COMPARATORS[sort]);
};
