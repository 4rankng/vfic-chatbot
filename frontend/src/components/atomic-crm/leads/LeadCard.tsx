import { Draggable } from "@hello-pangea/dnd";
import { useRedirect, RecordContextProvider } from "ra-core";
import { Card, CardContent } from "@/components/ui/card";
import { User, Briefcase } from "lucide-react";

import type { Lead } from "../types";

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
      className="cursor-pointer"
      {...provided?.draggableProps}
      {...provided?.dragHandleProps}
      ref={provided?.innerRef}
      onClick={handleClick}
    >
      <RecordContextProvider value={lead}>
        <Card
          className={`py-3 transition-all duration-200 ${
            snapshot?.isDragging
              ? "opacity-90 transform rotate-1 shadow-lg border-primary"
              : "shadow-sm hover:shadow-md"
          }`}
        >
          <CardContent className="px-3 flex flex-col gap-1">
            <div className="font-medium text-sm flex items-center gap-2">
              <User className="w-3 h-3 text-muted-foreground" />
              {lead.name}
            </div>
            {lead.desired_job && (
              <div className="text-xs text-muted-foreground flex items-center gap-2">
                <Briefcase className="w-3 h-3" />
                {lead.desired_job}
              </div>
            )}
            <div className="flex justify-between items-center mt-2">
              <span className="text-[10px] text-muted-foreground px-2 py-0.5 bg-muted rounded-full">
                Score: {lead.lead_score || "N/A"}
              </span>
              <span className="text-[10px] text-muted-foreground">
                {lead.updated_at ? new Date(lead.updated_at).toLocaleDateString() : ""}
              </span>
            </div>
          </CardContent>
        </Card>
      </RecordContextProvider>
    </div>
  );
};
