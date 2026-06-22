import { ListBase } from "ra-core";
import { CreateButton } from "@/components/admin/create-button";
import { TopToolbar } from "../layout/TopToolbar";

import { LeadListContent } from "./LeadListContent";

export const LeadList = () => {
  return (
    <ListBase perPage={100} sort={{ field: "updated_at", order: "DESC" }}>
      <TopToolbar>
        <div className="mr-auto" />
        <CreateButton />
      </TopToolbar>
      <div className="mt-4 px-4 pb-8">
        <LeadListContent />
      </div>
    </ListBase>
  );
};
