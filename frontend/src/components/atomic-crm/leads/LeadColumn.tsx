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
    <div className="flex-1 pb-8 min-w-[250px]">
      <div className="flex flex-col items-center">
        <h3 className="text-base font-medium">{stageLabel}</h3>
        <p className="text-sm text-muted-foreground">
          {leads.length} {leads.length === 1 ? "lead" : "leads"}
        </p>
      </div>
      <Droppable droppableId={stage}>
        {(droppableProvided, snapshot) => (
          <div
            ref={droppableProvided.innerRef}
            {...droppableProvided.droppableProps}
            className={`flex flex-col rounded-2xl mt-2 gap-2 min-h-[150px] p-2 ${
              snapshot.isDraggingOver ? "bg-muted" : "bg-card"
            }`}
          >
            {leads.map((lead, index) => (
              <LeadCard key={lead.id} lead={lead} index={index} />
            ))}
            {droppableProvided.placeholder}
          </div>
        )}
      </Droppable>
    </div>
  );
};
