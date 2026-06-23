import { useMemo, useState } from "react";
import { useListContext, useRefresh, ShowBase } from "ra-core";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ListPagination } from "@/components/admin";
import { RefreshCw, Users } from "lucide-react";

import { LEAD_STAGES, type Lead } from "../types";
import { LeadCard } from "./LeadCard";
import { LeadShowContent } from "./LeadShow";

export { LEAD_STAGES };

const compareLeads =
  (field: string, order: "ASC" | "DESC") => (a: Lead, b: Lead) => {
    const av = String((a as Record<string, unknown>)[field] ?? "");
    const bv = String((b as Record<string, unknown>)[field] ?? "");
    const cmp =
      field === "name"
        ? av.localeCompare(bv, "vi")
        : av < bv
          ? -1
          : av > bv
            ? 1
            : 0;
    return order === "DESC" ? -cmp : cmp;
  };

export const LeadListContent = () => {
  const { data: leads, isPending, error, sort, filterValues } = useListContext<Lead>();
  const [selectedLeadId, setSelectedLeadId] = useState<string | number | null>(null);
  const refresh = useRefresh();
  
  const filters = filterValues ?? {};
  const hasActiveStage = Boolean(filters.lead_stage);

  const sortedLeads = useMemo(() => {
    const list = [...(leads ?? [])];
    const field = sort?.field ?? "updated_at";
    const order = sort?.order ?? "DESC";
    return list.sort(compareLeads(field, order));
  }, [leads, sort]);

  if (isPending) {
    return (
      <div className="flex flex-col gap-px rounded-xl border overflow-hidden bg-border/50">
        {Array.from({ length: 6 }).map((_, i) => (
          <LeadCardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center text-sm text-destructive">
        Không tải được danh sách ứng viên.
      </div>
    );
  }

  if (!sortedLeads || sortedLeads.length === 0) {
    return (
      <EmptyState
        icon={<Users className="size-6" />}
        title="Chưa có ứng viên"
        description="Ứng viên được tạo tự động khi ứng viên nhắn tin qua Zalo. Nhấp vào một ứng viên để xem chi tiết."
        actions={
          <Button variant="outline" size="sm" onClick={() => refresh()}>
            <RefreshCw className="size-4" />
            Làm mới
          </Button>
        }
      />
    );
  }

  return (
    <>
      <div className="flex flex-col gap-px rounded-xl border border-border/50 bg-border/50 overflow-hidden shadow-sm">
        {sortedLeads.map((lead) => (
          <LeadCard 
            key={lead.id} 
            lead={lead} 
            showStageBadge={!hasActiveStage} 
            onClick={(l) => setSelectedLeadId(l.id)}
          />
        ))}
      </div>
      <ListPagination rowsPerPageOptions={[20, 50, 100]} className="pt-4" />
      <Sheet open={!!selectedLeadId} onOpenChange={(open) => !open && setSelectedLeadId(null)}>
        <SheetContent side="right" className="w-full sm:max-w-[480px] lg:max-w-[600px] p-0 overflow-y-auto border-l">
          {selectedLeadId && (
            <ShowBase resource="leads" id={selectedLeadId}>
              <div className="p-4 md:p-6 pb-20">
                <LeadShowContent />
              </div>
            </ShowBase>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
};

const LeadCardSkeleton = () => (
  <div className="flex items-center gap-3 bg-card px-4 py-4">
    <Skeleton shimmer className="size-9 shrink-0 rounded-full" />
    <div className="flex-1 space-y-2">
      <Skeleton shimmer className="h-4 w-1/3 rounded" />
      <Skeleton shimmer className="h-3 w-1/2 rounded" />
    </div>
  </div>
);
