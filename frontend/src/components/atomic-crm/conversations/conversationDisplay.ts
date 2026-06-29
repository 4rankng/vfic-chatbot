import type { Lead } from "../types";

export const getLeadStatusColor = (lead?: Lead | null) => {
  if (!lead || (!lead.name && !lead.phone))
    return { bg: "var(--surface-solid)", ink: "var(--ink-faint)" };
  if (!lead.phone || !lead.desired_job)
    return { bg: "var(--brand-light)", ink: "var(--brand)" };
  return { bg: "var(--success-light)", ink: "var(--success)" };
};
