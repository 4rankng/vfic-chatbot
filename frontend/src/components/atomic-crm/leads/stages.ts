import type { LucideIcon } from "lucide-react";
import {
  Ban,
  Briefcase,
  CheckCircle2,
  CircleDashed,
  FileText,
  Users,
  XCircle,
} from "lucide-react";

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

// Visual config for each recruitment stage — shared by the board column and any
// stage-aware UI. Icons are stored as component REFERENCES (not JSX elements) so
// this module can stay `.ts` and consumers render `<StageIcon className=… />`.
export type StageConfig = {
  bg: string;
  text: string;
  icon: LucideIcon;
};

export const STAGE_CONFIG: Record<string, StageConfig> = {
  NEW: {
    bg: "bg-slate-100 dark:bg-slate-800",
    text: "text-slate-700 dark:text-slate-300",
    icon: CircleDashed,
  },
  ENGAGED: {
    bg: "bg-blue-100 dark:bg-blue-900/30",
    text: "text-blue-700 dark:text-blue-300",
    icon: Users,
  },
  QUALIFIED: {
    bg: "bg-cyan-100 dark:bg-cyan-900/30",
    text: "text-cyan-700 dark:text-cyan-300",
    icon: CheckCircle2,
  },
  APPLIED: {
    bg: "bg-amber-100 dark:bg-amber-900/30",
    text: "text-amber-700 dark:text-amber-300",
    icon: FileText,
  },
  HIRED: {
    bg: "bg-emerald-100 dark:bg-emerald-900/30",
    text: "text-emerald-700 dark:text-emerald-300",
    icon: Briefcase,
  },
  LOST: {
    bg: "bg-rose-100 dark:bg-rose-900/30",
    text: "text-rose-700 dark:text-rose-300",
    icon: XCircle,
  },
  UNQUALIFIED: {
    bg: "bg-zinc-100 dark:bg-zinc-900/30",
    text: "text-zinc-700 dark:text-zinc-300",
    icon: Ban,
  },
};
