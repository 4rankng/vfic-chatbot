import type { Lead } from "../types";

export type LeadsByStage = Record<string, Lead[]>;

export const getLeadsByStage = (
  unorderedLeads: Lead[],
  leadStages: readonly { value: string; label: string }[],
) => {
  if (!leadStages) return {};
  const leadsByStage: Record<string, Lead[]> = unorderedLeads.reduce(
    (acc, lead) => {
      const stage = leadStages.find((s) => s.value === lead.lead_stage)
        ? lead.lead_stage
        : leadStages[0].value;
      if (!acc[stage]) acc[stage] = [];
      acc[stage].push(lead);
      return acc;
    },
    leadStages.reduce(
      (obj, stage) => ({ ...obj, [stage.value]: [] }),
      {} as Record<string, Lead[]>,
    ),
  );
  // sort by updated_at desc
  leadStages.forEach((stage) => {
    if (leadsByStage[stage.value]) {
      leadsByStage[stage.value] = leadsByStage[stage.value].sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
    }
  });
  return leadsByStage;
};
