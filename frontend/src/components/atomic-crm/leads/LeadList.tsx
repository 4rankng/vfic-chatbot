import { useDeferredValue, useState } from "react";

import { LeadListContent } from "./LeadListContent";
import { LeadsToolbar, type LeadSort } from "./LeadsToolbar";

const LeadPageHeader = ({ total }: { total: number }) => {
  return (
    <div className="flex items-center justify-between mb-4">
      <h1 className="text-xl font-semibold text-foreground">
        Ứng viên tiềm năng{" "}
        <span className="text-muted-foreground font-normal">
          ({total ?? 0})
        </span>
      </h1>
    </div>
  );
};

export const LeadList = () => {
  const [searchQuery, setSearchQuery] = useState("");
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const [sort, setSort] = useState<LeadSort>({
    field: "updated_at",
    order: "DESC",
  });
  const [total, setTotal] = useState(0);

  return (
    <div className="mt-4 px-4 pb-8">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <LeadPageHeader total={total} />
        <LeadsToolbar
          searchQuery={searchQuery}
          sort={sort}
          onSearchQueryChange={setSearchQuery}
          onSortChange={setSort}
        />
        <LeadListContent
          searchQuery={deferredSearchQuery}
          sort={sort}
          onTotalChange={setTotal}
        />
      </div>
    </div>
  );
};
