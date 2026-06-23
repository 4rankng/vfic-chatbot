import { Droppable } from "@hello-pangea/dnd";
import type { Lead } from "../types";
import { LeadCard } from "./LeadCard";
import { LEAD_STAGES } from "./LeadListContent";
import { STAGE_CONFIG } from "./stages";

export const LeadColumn = ({
  stage,
  leads,
}: {
  stage: string;
  leads: Lead[];
}) => {
  const stageLabel = LEAD_STAGES.find((s) => s.value === stage)?.label || stage;
  const config = STAGE_CONFIG[stage] || STAGE_CONFIG.NEW;
  const StageIcon = config.icon;

  return (
    <div className="flex-grow pb-8 min-w-[320px] bg-muted/20 border-0 rounded-2xl flex flex-col min-h-[600px] shadow-sm">
      <div
        className={`flex justify-between items-center px-4 py-3 rounded-t-2xl ${config.bg} ${config.text} mb-2`}
      >
        <div className="flex items-center gap-2">
          <StageIcon className="w-4 h-4" />
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
