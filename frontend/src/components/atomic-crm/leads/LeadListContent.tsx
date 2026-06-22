import { useListContext } from "ra-core";

import { LEAD_STAGES, type Lead } from "../types";
import { LeadCard } from "./LeadCard";

// Re-export so existing consumers (Dashboard) keep compiling while
// reading the single canonical source in types.ts — eliminates stage drift.
export { LEAD_STAGES };

export const LeadListContent = () => {
  const { data: leads, isPending } = useListContext<Lead>();

  if (isPending) return null;

  if (!leads || leads.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl bg-muted/20 px-6 py-16 text-center">
        <p className="font-mono text-sm font-semibold text-muted-dim">
          Chưa có khách hàng
        </p>
        <p className="mt-1 max-w-sm text-xs text-muted-foreground">
          Khi có khách hàng mới, họ sẽ xuất hiện tại đây. Nhấp vào một khách
          hàng để bắt đầu trò chuyện.
        </p>
      </div>
    );
  }

  return (
    <div className="flex w-full max-w-3xl flex-col gap-3">
      {leads.map((lead) => (
        <LeadCard key={lead.id} lead={lead} />
      ))}
    </div>
  );
};
