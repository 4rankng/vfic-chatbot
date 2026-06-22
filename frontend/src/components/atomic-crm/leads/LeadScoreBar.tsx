import { cn } from "@/lib/utils";
import { LEAD_SCORES, type LeadScoreValue } from "../types";

const scoreMeta = (score: LeadScoreValue | null | undefined) =>
  LEAD_SCORES.find((s) => s.value === score) ?? null;

/**
 * Categorical lead-score badge. The DB column `leads.lead_score` is a text
 * CHECK constraint with values `hot | warm | not_interested` — NOT a 0-100
 * number. This component renders the value as a coloured pill. `className`
 * is applied to the wrapper.
 */
export const LeadScoreBar = ({
  score,
  className,
}: {
  score: LeadScoreValue | null | undefined;
  className?: string;
}) => {
  const meta = scoreMeta(score);
  if (!meta) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium text-muted-foreground bg-muted",
          className,
        )}
      >
        Score: N/A
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white",
        meta.color,
        className,
      )}
    >
      {meta.label}
    </span>
  );
};
