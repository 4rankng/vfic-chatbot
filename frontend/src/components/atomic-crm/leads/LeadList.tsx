import { ListBase, useListContext } from "ra-core";
import { useSearchParams } from "react-router";
import { CreateButton } from "@/components/admin/create-button";
import { useIsMobile } from "@/hooks/use-mobile";

import { LeadListContent } from "./LeadListContent";
import { LeadsSummaryHeader } from "./LeadsSummaryHeader";
import { LeadsToolbar } from "./LeadsToolbar";

const LeadPageHeader = () => {
  const { total } = useListContext();
  return (
    <div className="flex items-center justify-between mb-4">
      <h1 className="text-xl font-semibold text-foreground">
        Ứng viên tiềm năng <span className="text-muted-foreground font-normal">({total ?? 0})</span>
      </h1>
      <CreateButton label="Thêm ứng viên" />
    </div>
  );
};

export const LeadList = () => {
  const [searchParams] = useSearchParams();
  const isMobile = useIsMobile();
  const wantBoard = searchParams.get("display") === "board";

  const isBoard = wantBoard && !isMobile;

  return (
    <ListBase perPage={100} sort={{ field: "updated_at", order: "DESC" }}>
      <div className="mt-4 px-4 pb-8">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
          <LeadPageHeader />
          <LeadsToolbar />
          {!isBoard && <LeadsSummaryHeader />}
          {/* Phase 4: isBoard ? <LeadBoard /> : <LeadListContent /> */}
          <LeadListContent />
        </div>
      </div>
    </ListBase>
  );
};
