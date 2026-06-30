import { Avatar as ShadcnAvatar } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { UserRound } from "lucide-react";
import { useRecordContext } from "ra-core";

import type { Lead } from "../types";

const priorityTone = (score: Lead["lead_score"]) => {
  if (score === "hot") {
    return "border-rose-300/70 bg-rose-100/80 text-rose-700 dark:border-rose-500/45 dark:bg-rose-950/45 dark:text-rose-300";
  }
  if (score === "warm") {
    return "border-amber-300/70 bg-amber-100/80 text-amber-700 dark:border-amber-500/45 dark:bg-amber-950/45 dark:text-amber-300";
  }
  return "border-border bg-muted text-muted-foreground";
};

export const LeadAvatar = ({
  record,
  size = "md",
  className,
}: {
  record?: Lead;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
}) => {
  const ctx = useRecordContext<Lead>();
  const r = record ?? ctx;
  const sizeClass =
    size === "xl"
      ? "size-20 text-2xl"
      : size === "lg"
        ? "size-14 text-lg"
        : size === "sm"
          ? "size-8 text-xs"
          : "size-10 text-sm";
  if (!r) return null;
  return (
    <ShadcnAvatar
      className={cn(
        sizeClass,
        "items-center justify-center border ring-1 ring-border/60",
        priorityTone(r.lead_score),
        className,
      )}
    >
      <UserRound className="size-1/2" aria-hidden="true" />
    </ShadcnAvatar>
  );
};
