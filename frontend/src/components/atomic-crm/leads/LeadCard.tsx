import { useRedirect, RecordContextProvider } from "ra-core";
import { cn } from "@/lib/utils";

import type { Lead } from "../types";
import type { LeadScoreValue } from "../types";
import { getRelativeTimeString } from "./leadUtils";
import { LeadAvatar } from "./LeadAvatar";
import { LeadScoreBar } from "./LeadScoreBar";
import { LeadStageMenu } from "./LeadStageMenu";

// Categorical score accent for the dense card's left rail. `leads.lead_score`
// is CHECK-constrained to hot | warm | not_interested (NOT numeric). This maps
// each value to a single categorical colour — preserved from the legacy card.
const SCORE_CARD_STYLE: Record<LeadScoreValue, { accent: string }> = {
  hot: { accent: "before:bg-rose-400/80 dark:before:bg-rose-500/70" },
  warm: { accent: "before:bg-amber-400/80 dark:before:bg-amber-500/70" },
  not_interested: {
    accent: "before:bg-zinc-400/70 dark:before:bg-zinc-500/70",
  },
};

export const LeadCard = ({ lead }: { lead: Lead }) => {
  if (!lead) return null;
  return <LeadCardContent lead={lead} />;
};

/**
 * Dense triage row — the shared lead atom. Clicking anywhere except the ⋯ stage
 * menu opens the lead's show page.
 */
export const LeadCardContent = ({ lead }: { lead: Lead }) => {
  const redirect = useRedirect();
  const handleClick = () => {
    redirect(`/leads/${lead.id}/show`, undefined, undefined, undefined, {
      _scrollToTop: false,
    });
  };

  const scoreStyle = lead.lead_score
    ? SCORE_CARD_STYLE[lead.lead_score as LeadScoreValue]
    : null;
  const updatedAt = lead.updated_at
    ? getRelativeTimeString(lead.updated_at, "vi")
    : null;

  return (
    <div className="cursor-pointer select-none" onClick={handleClick}>
      <RecordContextProvider value={lead}>
        <div
          className={cn(
            "group relative flex items-center gap-3 rounded-xl border px-3 py-2.5",
            "border-zinc-200/60 bg-white/80 backdrop-blur dark:border-zinc-800/60 dark:bg-zinc-900/60",
            "transition-colors hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40",
            "before:absolute before:left-0 before:top-2.5 before:bottom-2.5 before:w-1 before:rounded-full before:content-['']",
            scoreStyle?.accent ?? "before:bg-transparent",
          )}
        >
          <LeadAvatar record={lead} size="sm" className="size-9 shrink-0" />

          <div className="min-w-0 flex-1">
            <div
              className={cn(
                "truncate text-sm font-semibold text-foreground",
                !lead.name && "font-medium italic text-muted-foreground",
              )}
            >
              {lead.name ||
                `Khách hàng chưa biết · đuôi ${(lead.zalo_id || "").slice(-4)}`}
            </div>
            <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
              {lead.desired_job ? (
                <span className="truncate">{lead.desired_job}</span>
              ) : (
                <span className="italic text-muted-foreground/70">
                  Chưa rõ công việc
                </span>
              )}
              {updatedAt && (
                <>
                  <span className="shrink-0 text-muted-foreground/50">·</span>
                  <span className="shrink-0 tabular-nums">{updatedAt}</span>
                </>
              )}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <LeadScoreBar score={lead.lead_score} />
            <LeadStageMenu />
          </div>
        </div>
      </RecordContextProvider>
    </div>
  );
};
