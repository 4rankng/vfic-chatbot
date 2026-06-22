import { Droppable } from "@hello-pangea/dnd";
import type { Lead } from "../types";
import { LeadCard } from "./LeadCard";
import { LEAD_STAGES } from "./LeadListContent";
import {
  CircleDashed,
  Users,
  CheckCircle2,
  FileText,
  Briefcase,
  XCircle,
  Ban,
} from "lucide-react";

const STAGE_CONFIG: Record<
  string,
  { bg: string; text: string; icon: React.ReactNode }
> = {
  NEW: {
    bg: "bg-slate-100 dark:bg-slate-800",
    text: "text-slate-700 dark:text-slate-300",
    icon: <CircleDashed className="w-4 h-4" />,
  },
  ENGAGED: {
    bg: "bg-blue-100 dark:bg-blue-900/30",
    text: "text-blue-700 dark:text-blue-300",
    icon: <Users className="w-4 h-4" />,
  },
  QUALIFIED: {
    bg: "bg-cyan-100 dark:bg-cyan-900/30",
    text: "text-cyan-700 dark:text-cyan-300",
    icon: <CheckCircle2 className="w-4 h-4" />,
  },
  APPLIED: {
    bg: "bg-amber-100 dark:bg-amber-900/30",
    text: "text-amber-700 dark:text-amber-300",
    icon: <FileText className="w-4 h-4" />,
  },
  HIRED: {
    bg: "bg-emerald-100 dark:bg-emerald-900/30",
    text: "text-emerald-700 dark:text-emerald-300",
    icon: <Briefcase className="w-4 h-4" />,
  },
  LOST: {
    bg: "bg-rose-100 dark:bg-rose-900/30",
    text: "text-rose-700 dark:text-rose-300",
    icon: <XCircle className="w-4 h-4" />,
  },
  UNQUALIFIED: {
    bg: "bg-zinc-100 dark:bg-zinc-900/30",
    text: "text-zinc-700 dark:text-zinc-300",
    icon: <Ban className="w-4 h-4" />,
  },
};

export const LeadColumn = ({
  stage,
  leads,
}: {
  stage: string;
  leads: Lead[];
}) => {
  const stageLabel = LEAD_STAGES.find((s) => s.value === stage)?.label || stage;
  const config = STAGE_CONFIG[stage] || STAGE_CONFIG.NEW;

  return (
    <div className="flex-grow pb-8 min-w-[320px] bg-muted/20 border-0 rounded-2xl flex flex-col min-h-[600px] shadow-sm">
      <div
        className={`flex justify-between items-center px-4 py-3 rounded-t-2xl ${config.bg} ${config.text} mb-2`}
      >
        <div className="flex items-center gap-2">
          {config.icon}
          <h3 className="font-semibold text-[13px] tracking-wide uppercase">
            {stageLabel}
          </h3>
        </div>
        <div className="bg-background/60 backdrop-blur-sm shadow-sm text-xs font-bold px-2 py-0.5 rounded-md">
          {leads.length}
        </div>
      </div>
      <Droppable droppableId={stage}>
        {(droppableProvided, snapshot) => (
          <div
            ref={droppableProvided.innerRef}
            {...droppableProvided.droppableProps}
            className={`flex flex-col flex-1 gap-3 min-h-[250px] transition-all rounded-xl p-3 ${
              snapshot.isDraggingOver ? "bg-muted-dim/10" : ""
            }`}
          >
            {leads.map((lead) => (
              <LeadCard key={lead.id} lead={lead} />
            ))}
            {leads.length === 0 && !snapshot.isDraggingOver && (
              <div className="flex-1 flex flex-col items-center justify-center p-6 rounded-xl bg-card/20 text-center text-muted-dim">
                <span className="font-mono text-xs font-semibold">
                  Chưa có khách hàng
                </span>
              </div>
            )}
            {droppableProvided.placeholder}
          </div>
        )}
      </Droppable>
    </div>
  );
};
