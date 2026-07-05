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

import { LEAD_STAGES, type Lead } from "../types";

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

    const updateData: Partial<Lead> & { closed_reason?: string } = {
      lead_stage: stage,
    };

    if (stage === "CLOSED") {
      const reason = window.prompt("Lý do đóng ứng viên này?");
      if (reason === null) return; // User cancelled
      if (reason) updateData.closed_reason = reason;
    }

    update(
      "leads",
      {
        id: lead.id,
        data: updateData,
        previousData: lead,
      },
      {
        mutationMode: "pessimistic",
        onSuccess: (updatedLead) => {
          window.dispatchEvent(
            new CustomEvent("vfic:lead-list-refresh", {
              detail: { lead_id: updatedLead.id },
            }),
          );
          notify("Đã cập nhật giai đoạn", { type: "success" });
        },
        onError: (error) =>
          notify(
            isRlsError(error)
              ? "Bạn không có quyền chuyển ứng viên sang giai đoạn này"
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
          // Always visible — hover-reveal (`group-hover:opacity-100`) made the
          // trigger undiscoverable on touch (no hover state). Mirrors the
          // always-visible treatment already applied to the call button.
          className={cn(
            "inline-flex size-11 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition",
            "hover:border-border hover:bg-card hover:text-foreground hover:shadow-[0_2px_8px_rgba(26,34,40,0.08),0_1px_2px_rgba(26,34,40,0.06)]",
            "dark:hover:border-border/80 dark:hover:bg-accent/20 dark:hover:shadow-[0_2px_10px_rgba(0,0,0,0.28)]",
            "disabled:cursor-wait disabled:opacity-50",
          )}
        >
          <MoreHorizontal className="size-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-52 border-border bg-popover shadow-[0_12px_28px_rgba(26,34,40,0.16),0_4px_10px_rgba(26,34,40,0.08)] dark:border-border/80 dark:shadow-[0_16px_32px_rgba(0,0,0,0.44)]"
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
