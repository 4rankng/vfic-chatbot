import { cn } from "@/lib/utils";
import { LEAD_STAGES, type LeadStageValue } from "../types";

const STAGE_MAP: Record<string, { label: string; classes: string }> =
  LEAD_STAGES.reduce(
    (acc, s) => ({
      ...acc,
      [s.value]: {
        label: s.label,
        classes: cn(s.color, "text-white"),
      },
    }),
    {} as Record<string, { label: string; classes: string }>,
  );

export const LeadStageBadge = ({
  stage,
  className,
}: {
  stage: LeadStageValue | string;
  className?: string;
}) => {
  const entry = STAGE_MAP[stage] ?? {
    label: stage,
    classes: "bg-muted text-muted-foreground",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
        entry.classes,
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-white/80" />
      {entry.label}
    </span>
  );
};
