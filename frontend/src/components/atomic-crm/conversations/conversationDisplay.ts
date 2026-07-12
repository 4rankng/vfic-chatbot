import { type Lead } from "../types";

/** Return the external Zalo recipient ID stored by the channel provider. */
export const getZaloUserId = (
  zaloChatId: string | null | undefined,
  zaloChannel?: string,
) => {
  if (!zaloChatId) return "";
  return zaloChannel === "oa" && zaloChatId.startsWith("oa:")
    ? zaloChatId.slice("oa:".length)
    : zaloChatId;
};

export const getLeadStatusColor = (lead?: Lead | null) => {
  if (!lead)
    return {
      bg: "var(--workspace-surface-muted)",
      ink: "var(--workspace-ink-muted)",
    };
  if (lead.lead_score === "hot")
    return { bg: "var(--lead-hot-bg)", ink: "var(--lead-hot-ink)" };
  if (lead.lead_score === "warm")
    return { bg: "var(--lead-warm-bg)", ink: "var(--lead-warm-ink)" };
  return {
    bg: "var(--workspace-surface-muted)",
    ink: "var(--workspace-ink-muted)",
  };
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
