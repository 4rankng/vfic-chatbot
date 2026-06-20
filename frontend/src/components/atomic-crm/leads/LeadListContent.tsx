import { DragDropContext, type OnDragEndResponder } from "@hello-pangea/dnd";
import isEqual from "lodash/isEqual";
import { useDataProvider, useListContext, type DataProvider } from "ra-core";
import { useEffect, useState } from "react";

import type { Lead } from "../types";
import { LeadColumn } from "./LeadColumn";
import type { LeadsByStage } from "./stages";
import { getLeadsByStage } from "./stages";

export const LEAD_STAGES = [
  { value: "NEW", label: "New" },
  { value: "QUALIFIED", label: "Qualified" },
  { value: "CONTACTED", label: "Contacted" },
  { value: "INTERVIEWING", label: "Interviewing" },
  { value: "OFFERED", label: "Offered" },
  { value: "HIRED", label: "Hired" },
  { value: "REJECTED", label: "Rejected" },
];

export const LeadListContent = () => {
  const { data: unorderedLeads, isPending, refetch } = useListContext<Lead>();
  const dataProvider = useDataProvider();

  const [leadsByStage, setLeadsByStage] = useState<LeadsByStage>(
    getLeadsByStage([], LEAD_STAGES),
  );

  useEffect(() => {
    if (unorderedLeads) {
      const newLeadsByStage = getLeadsByStage(unorderedLeads, LEAD_STAGES);
      if (!isEqual(newLeadsByStage, leadsByStage)) {
        setLeadsByStage(newLeadsByStage);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unorderedLeads]);

  if (isPending) return null;

  const onDragEnd: OnDragEndResponder = (result) => {
    const { destination, source } = result;

    if (!destination) return;
    if (destination.droppableId === source.droppableId && destination.index === source.index) return;

    const sourceStage = source.droppableId;
    const destinationStage = destination.droppableId;
    const sourceLead = leadsByStage[sourceStage][source.index]!;

    // compute local state change synchronously
    setLeadsByStage(
      updateLeadStageLocal(
        sourceLead,
        { stage: sourceStage, index: source.index },
        { stage: destinationStage, index: destination.index },
        leadsByStage,
      ),
    );

    // persist the changes
    updateLeadStage(sourceLead, destinationStage, dataProvider).then(() => {
      refetch();
    });
  };

  return (
    <DragDropContext onDragEnd={onDragEnd}>
      <div className="flex gap-4">
        {LEAD_STAGES.map((stage) => (
          <LeadColumn
            stage={stage.value}
            leads={leadsByStage[stage.value] || []}
            key={stage.value}
          />
        ))}
      </div>
    </DragDropContext>
  );
};

const updateLeadStageLocal = (
  sourceLead: Lead,
  source: { stage: string; index: number },
  destination: { stage: string; index?: number },
  leadsByStage: LeadsByStage,
) => {
  if (source.stage === destination.stage) {
    const column = [...(leadsByStage[source.stage] || [])];
    column.splice(source.index, 1);
    column.splice(destination.index ?? column.length + 1, 0, sourceLead);
    return { ...leadsByStage, [destination.stage]: column };
  } else {
    const sourceColumn = [...(leadsByStage[source.stage] || [])];
    const destinationColumn = [...(leadsByStage[destination.stage] || [])];
    sourceColumn.splice(source.index, 1);
    destinationColumn.splice(destination.index ?? destinationColumn.length + 1, 0, sourceLead);
    return {
      ...leadsByStage,
      [source.stage]: sourceColumn,
      [destination.stage]: destinationColumn,
    };
  }
};

const updateLeadStage = async (
  source: Lead,
  destinationStage: string,
  dataProvider: DataProvider,
) => {
  // Drop index-dependent code entirely.
  // Just update the lead_stage.
  await dataProvider.update("leads", {
    id: source.id,
    data: { 
      lead_stage: destinationStage,
      updated_at: new Date().toISOString()
    },
    previousData: source,
  });
};
