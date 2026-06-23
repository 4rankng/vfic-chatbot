import { useMemo, useState } from "react";
import { useListContext } from "ra-core";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

import { LEAD_STAGES, type Lead } from "../types";
import { LeadCard } from "./LeadCard";
import { getLeadsByStage } from "./stages";

// Re-export so existing consumers (Dashboard, MobileDashboard, LeadColumn,
// LeadStageBadge) keep compiling while reading the single canonical source in
// types.ts — eliminates stage drift. DO NOT remove.
export { LEAD_STAGES };

// Compare two leads by a sort field. Date fields are ISO-8601 strings, so
// lexicographic comparison == chronological. `name` uses locale-aware vi sort.
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
  const { data: leads, isPending, error, sort } = useListContext<Lead>();

  // Bucket by stage, then re-sort each bucket by the active toolbar sort so the
  // Sort control governs within-group order (getLeadsByStage defaults to
  // updated_at desc, which matches the list default).
  const groups = useMemo(() => {
    const buckets = getLeadsByStage(leads ?? [], LEAD_STAGES);
    const field = sort?.field ?? "updated_at";
    const order = sort?.order ?? "DESC";
    for (const key of Object.keys(buckets)) {
      buckets[key] = [...buckets[key]].sort(compareLeads(field, order));
    }
    return buckets;
  }, [leads, sort]);

  if (isPending) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <LeadCardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center text-sm text-destructive">
        Không tải được danh sách khách hàng.
      </div>
    );
  }

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

  // Density-first: only populated stage groups render. The LeadsSummaryHeader
  // already conveys the full 7-stage funnel; empty groups would be noise here.
  const visibleStages = LEAD_STAGES.filter(
    (s) => (groups[s.value]?.length ?? 0) > 0,
  );

  return (
    <div className="flex flex-col gap-3">
      {visibleStages.map((s) => (
        <StageGroup key={s.value} stage={s.value} leads={groups[s.value]} />
      ))}
    </div>
  );
};

const StageGroup = ({ stage, leads }: { stage: string; leads: Lead[] }) => {
  const [open, setOpen] = useState(true);
  const meta = LEAD_STAGES.find((s) => s.value === stage);

  return (
    <section className="rounded-xl border border-zinc-200/60 bg-white/40 p-3 backdrop-blur dark:border-zinc-800/60 dark:bg-zinc-900/30">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-1 py-1 text-left"
        aria-expanded={open}
      >
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            !open && "-rotate-90",
          )}
        />
        <span className="text-sm font-semibold text-foreground">
          {meta?.label ?? stage}
        </span>
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-muted-foreground">
          {leads.length}
        </span>
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-2">
          {leads.map((lead) => (
            <LeadCard key={lead.id} lead={lead} />
          ))}
        </div>
      )}
    </section>
  );
};

const LeadCardSkeleton = () => (
  <div className="flex items-center gap-3 rounded-xl border border-zinc-200/60 bg-white/60 px-3 py-2.5 dark:border-zinc-800/60 dark:bg-zinc-900/40">
    <div className="size-9 shrink-0 animate-pulse rounded-full bg-muted" />
    <div className="flex-1 space-y-2">
      <div className="h-3 w-1/3 animate-pulse rounded bg-muted" />
      <div className="h-2.5 w-1/2 animate-pulse rounded bg-muted/70" />
    </div>
  </div>
);
