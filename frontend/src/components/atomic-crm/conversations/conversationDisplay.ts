import type { Lead } from "../types";

export const getLeadStatusColor = (lead?: Lead | null) => {
  if (!lead) return { bg: "var(--surface-solid)", ink: "var(--ink-faint)" };
  if (lead.lead_score === "hot")
    return { bg: "rgba(244, 63, 94, 0.16)", ink: "#e11d48" };
  if (lead.lead_score === "warm")
    return { bg: "rgba(245, 158, 11, 0.18)", ink: "#d97706" };
  return { bg: "rgba(100, 116, 139, 0.14)", ink: "#64748b" };
};
