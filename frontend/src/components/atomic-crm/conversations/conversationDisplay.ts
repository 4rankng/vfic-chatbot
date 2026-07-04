import { LEAD_SCORES, type Lead } from "../types";

export const getLeadStatusColor = (lead?: Lead | null) => {
  if (!lead) return { bg: "var(--surface-solid)", ink: "var(--ink-faint)" };
  if (lead.lead_score === "hot")
    return { bg: "var(--lead-hot-bg)", ink: "var(--lead-hot-ink)" };
  if (lead.lead_score === "warm")
    return { bg: "var(--lead-warm-bg)", ink: "var(--lead-warm-ink)" };
  return { bg: "var(--lead-cold-bg)", ink: "var(--lead-cold-ink)" };
};

// Non-color priority cue for the inbox row: a labelled chip whose TEXT conveys
// the tier (readable without color, for colour-blind users). `tone` drives the
// chip tint via the lead-priority CSS vars; the label is the accessible signal.
// Reuses the canonical LEAD_SCORES labels. Returns null when no score is set.
export const getLeadPriorityChip = (
  lead?: Lead | null,
): { label: string; tone: "hot" | "warm" | "cold" } | null => {
  const score = lead?.lead_score;
  if (!score) return null;
  const label = LEAD_SCORES.find((s) => s.value === score)?.label;
  if (!label) return null;
  const tone = score === "hot" ? "hot" : score === "warm" ? "warm" : "cold";
  return { label, tone };
};
