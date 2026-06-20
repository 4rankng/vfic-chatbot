import { cn } from "@/lib/utils";

const SCORE_THRESHOLDS = [
  { max: 30, label: "Cold", classes: "bg-rose-500" },
  { max: 60, label: "Warm", classes: "bg-amber-500" },
  { max: 85, label: "Hot", classes: "bg-blue-500" },
  { max: 101, label: "Excellent", classes: "bg-emerald-500" },
];

const scoreMeta = (score: number) =>
  SCORE_THRESHOLDS.find((t) => score <= t.max) ?? SCORE_THRESHOLDS[0];

export const LeadScoreBar = ({
  score,
  className,
  showLabel = true,
}: {
  score: number;
  className?: string;
  showLabel?: boolean;
}) => {
  const safe = Math.max(0, Math.min(100, Math.round(score || 0)));
  const meta = scoreMeta(safe);
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {showLabel ? (
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-muted-foreground">
            Lead score
          </span>
          <span className="flex items-center gap-2">
            <span className={cn("font-semibold tabular-nums", meta.classes.replace("bg-", "text-"))}>
              {safe}
            </span>
            <span className="text-muted-foreground">/ 100</span>
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white",
                meta.classes,
              )}
            >
              {meta.label}
            </span>
          </span>
        </div>
      ) : null}
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full transition-all duration-500", meta.classes)}
          style={{ width: `${safe}%` }}
          aria-label={`Lead score ${safe} out of 100`}
        />
      </div>
    </div>
  );
};

export const LeadScoreInline = ({ score }: { score: number }) => {
  const safe = Math.max(0, Math.min(100, Math.round(score || 0)));
  const meta = scoreMeta(safe);
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={cn("size-2 rounded-full", meta.classes)} />
      <span className="font-medium tabular-nums">{safe}</span>
    </span>
  );
};
