import { Droppable } from "@hello-pangea/dnd";

import type { Lead } from "../types";
import { LeadCard } from "./LeadCard";
import { LEAD_STAGES } from "./LeadListContent";

export const LeadColumn = ({
  stage,
  leads,
}: {
  stage: string;
  leads: Lead[];
}) => {
  const stageLabel = LEAD_STAGES.find((s) => s.value === stage)?.label || stage;

  return (
    <div className="flex-grow pb-8 min-w-[280px] bg-muted/40 border border-border/50 rounded-2xl p-3 min-h-[600px] flex flex-col gap-2">
      <div className="flex justify-between items-baseline border-b border-border/60 pb-2.5 mb-2 px-1">
        <h3
          className={`font-display text-lg font-bold tracking-wider uppercase ${stage === "QUALIFIED" ? "text-primary" : "text-foreground"}`}
        >
          {stageLabel}
        </h3>
        <span className="font-mono text-xs font-semibold text-muted-foreground">
          {leads.length} khách hàng
        </span>
      </div>
      <Droppable droppableId={stage}>
        {(droppableProvided, snapshot) => (
          <div
            ref={droppableProvided.innerRef}
            {...droppableProvided.droppableProps}
            className={`flex flex-col flex-1 gap-2 min-h-[250px] transition-all rounded-xl p-1 ${
              snapshot.isDraggingOver ? "bg-muted-dim/10" : ""
            }`}
          >
            {leads.map((lead, index) => (
              <LeadCard key={lead.id} lead={lead} index={index} />
            ))}
            {leads.length === 0 && !snapshot.isDraggingOver && (
              <div className="flex-1 border border-dashed border-border/70 flex flex-col items-center justify-center p-6 rounded-xl bg-card/20 text-center text-muted-dim">
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
