import { ListBase } from "ra-core";
import { CreateButton } from "@/components/admin/create-button";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { TopToolbar } from "../layout/TopToolbar";

import { LeadListContent } from "./LeadListContent";

export const LeadList = () => {
  return (
    <ListBase perPage={100} sort={{ field: "updated_at", order: "DESC" }}>
      <TopToolbar>
        <h2 className="text-xl font-semibold mr-auto">Leads Pipeline</h2>
        <CreateButton />
      </TopToolbar>
      <div className="mt-4 flex-1 h-full">
        <ScrollArea className="w-full whitespace-nowrap h-[calc(100vh-160px)]">
          <div className="flex w-max min-w-full px-4">
            <LeadListContent />
          </div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
      </div>
    </ListBase>
  );
};
