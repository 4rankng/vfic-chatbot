import { useNotify, useRecordContext, useUpdate } from "ra-core";
import { MoreHorizontal } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import type { Lead } from "../types";
import { LEAD_STAGES } from "./LeadListContent";

// PostgREST emits HTTP 42501 (insufficient_privilege) when an RLS policy blocks
// the write. Match broadly so a permission failure never surfaces as a generic
// "something went wrong".
const isRlsError = (error: unknown): boolean => {
  if (!error) return false;
  const e = error as { message?: string; status?: number; code?: string };
  const text = `${e.message ?? ""} ${e.code ?? ""}`.toLowerCase();
  return (
    e.status === 42501 ||
    /42501|insufficient_privilege|permission denied|policy|rls/.test(text)
  );
};

/**
 * Per-card stage advance menu (reads the lead from RecordContext). Selecting a
 * stage fires one optimistic update; the cached list patches in place, so the
 * stage moves without a reload. On an RLS rejection (42501) ra-core rolls back
 * and we surface a stage-specific toast.
 */
export const LeadStageMenu = () => {
  const lead = useRecordContext<Lead>();
  const notify = useNotify();
  const [update, { isPending }] = useUpdate<Lead>();

  if (!lead) return null;

  const handleSelect = (stage: string) => {
    if (isPending || stage === lead.lead_stage) return;
    update(
      "leads",
      {
        id: lead.id,
        data: { lead_stage: stage },
        previousData: lead,
      },
      {
        mutationMode: "optimistic",
        onSuccess: () => notify("Đã cập nhật giai đoạn", { type: "success" }),
        onError: (error) =>
          notify(
            isRlsError(error)
              ? "Bạn không có quyền chuyển khách hàng sang giai đoạn này"
              : "Không thể cập nhật giai đoạn",
            { type: "error" },
          ),
      },
    );
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Đổi giai đoạn"
          disabled={isPending}
          onClick={(e) => e.stopPropagation()}
          className={cn(
            "inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition",
            "opacity-0 focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100",
            "hover:bg-muted hover:text-foreground",
            "disabled:cursor-wait disabled:opacity-50",
          )}
        >
          <MoreHorizontal className="size-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-52"
        onClick={(e) => e.stopPropagation()}
      >
        <DropdownMenuLabel>Chuyển giai đoạn</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {LEAD_STAGES.map((stage) => (
          <DropdownMenuCheckboxItem
            key={stage.value}
            checked={stage.value === lead.lead_stage}
            disabled={isPending}
            onCheckedChange={(checked) => {
              if (checked) handleSelect(stage.value);
            }}
          >
            {stage.label}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
