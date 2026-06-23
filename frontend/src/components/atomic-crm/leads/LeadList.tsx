import { ListBase } from "ra-core";
import { useSearchParams } from "react-router";
import { CreateButton } from "@/components/admin/create-button";
import { useIsMobile } from "@/hooks/use-mobile";
import { TopToolbar } from "../layout/TopToolbar";

import { LeadListContent } from "./LeadListContent";
import { LeadsSummaryHeader } from "./LeadsSummaryHeader";
import { LeadsToolbar } from "./LeadsToolbar";

export const LeadList = () => {
  const [searchParams] = useSearchParams();
  const isMobile = useIsMobile();
  const wantBoard = searchParams.get("display") === "board";

  // The Kanban board is Phase-4-gated (opt-in, desktop-only). It is NOT built
  // yet — gated behind a stakeholder decision. `isBoard` is the Phase-4 hook
  // point: when <LeadBoard/> ships, render it here. Mobile ALWAYS renders the
  // list regardless of ?display=, so a shared board URL never dead-ends.
  const isBoard = wantBoard && !isMobile;

  return (
    <ListBase perPage={100} sort={{ field: "updated_at", order: "DESC" }}>
      <TopToolbar>
        <div className="mr-auto" />
        <CreateButton />
      </TopToolbar>
      <div className="mt-4 px-4 pb-8">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
          <LeadsToolbar />
          {!isBoard && <LeadsSummaryHeader />}
          {/* Phase 4: isBoard ? <LeadBoard /> : <LeadListContent /> */}
          <LeadListContent />
        </div>
      </div>
    </ListBase>
  );
};
