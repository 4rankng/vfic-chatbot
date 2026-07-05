import { type Lead } from "../types";

export const getLeadStatusColor = (lead?: Lead | null) => {
  if (!lead) return { bg: "var(--surface-solid)", ink: "var(--ink-faint)" };
  if (lead.lead_score === "hot")
    return { bg: "var(--lead-hot-bg)", ink: "var(--lead-hot-ink)" };
  if (lead.lead_score === "warm")
    return { bg: "var(--lead-warm-bg)", ink: "var(--lead-warm-ink)" };
  return { bg: "var(--lead-cold-bg)", ink: "var(--lead-cold-ink)" };
};

// Inbox rows show one recruiter-facing priority state. The backend still keeps
// hot/warm as separate scores, but the list should not expose two priority tiers.
export const getLeadPriorityChip = (
  lead?: Lead | null,
): { label: string; tone: "hot" | "warm" | "cold" } | null => {
  const score = lead?.lead_score;
  if (!score) return null;
  if (score === "hot" || score === "warm") {
    return { label: "Ưu tiên", tone: "warm" };
  }
  if (score === "not_interested") {
    return { label: "Không quan tâm", tone: "cold" };
  }
  return null;
};
