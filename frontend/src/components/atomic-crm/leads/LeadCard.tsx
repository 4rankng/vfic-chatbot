import { Draggable } from "@hello-pangea/dnd";
import { useRedirect, RecordContextProvider } from "ra-core";
import { Card, CardContent } from "@/components/ui/card";

import type { Lead } from "../types";
import { LeadScoreBar } from "./LeadScoreBar";

export const LeadCard = ({ lead, index }: { lead: Lead; index: number }) => {
  if (!lead) return null;

  return (
    <Draggable draggableId={String(lead.id)} index={index}>
      {(provided, snapshot) => (
        <LeadCardContent provided={provided} snapshot={snapshot} lead={lead} />
      )}
    </Draggable>
  );
};

export const LeadCardContent = ({
  provided,
  snapshot,
  lead,
}: {
  provided?: any;
  snapshot?: any;
  lead: Lead;
}) => {
  const redirect = useRedirect();
  const handleClick = () => {
    redirect(`/leads/${lead.id}/show`, undefined, undefined, undefined, {
      _scrollToTop: false,
    });
  };

  return (
    <div
      className="cursor-pointer select-none"
      {...provided?.draggableProps}
      {...provided?.dragHandleProps}
      ref={provided?.innerRef}
      onClick={handleClick}
    >
      <RecordContextProvider value={lead}>
        <Card
          className={`py-3.5 border border-border bg-card transition-all duration-200 rounded-xl ${
            snapshot?.isDragging
              ? "opacity-90 transform rotate-1 shadow-md border-primary/80 ring-3 ring-primary/15"
              : "shadow-xs hover:-translate-y-0.5 hover:shadow-sm hover:border-muted-dim/40"
          }`}
        >
          <CardContent className="px-3.5 py-0 flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <div
                className={`text-sm ${lead.name ? "font-semibold text-foreground" : "italic text-muted-dim font-medium"}`}
              >
                {lead.name ||
                  `Unknown lead · ending ${(lead.zalo_id || "").slice(-4)}`}
              </div>
            </div>

            {lead.desired_job && (
              <div className="bg-muted/40 border border-border/50 rounded-lg px-2.5 py-2 mt-1 text-xs text-muted-foreground/90 font-medium line-clamp-2">
                {lead.desired_job}
              </div>
            )}

            <div className="flex justify-between items-center mt-3 pt-2.5 border-t border-border/50">
              <LeadScoreBar score={lead.lead_score} />
              <span className="font-mono text-[10px] font-semibold text-muted-dim">
                {lead.updated_at
                  ? new Date(lead.updated_at).toLocaleDateString()
                  : ""}
              </span>
            </div>
          </CardContent>
        </Card>
      </RecordContextProvider>
    </div>
  );
};
