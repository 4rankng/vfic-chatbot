import { useRedirect, RecordContextProvider } from "ra-core";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import type { Lead } from "../types";
import type { LeadScoreValue } from "../types";

const SCORE_CARD_STYLE: Record<
  LeadScoreValue,
  { tint: string; accent: string }
> = {
  hot: {
    tint: "bg-rose-50/70 dark:bg-rose-950/40",
    accent: "before:bg-rose-400/80 dark:before:bg-rose-500/70",
  },
  warm: {
    tint: "bg-amber-50/70 dark:bg-amber-950/40",
    accent: "before:bg-amber-400/80 dark:before:bg-amber-500/70",
  },
  not_interested: {
    tint: "bg-zinc-100/60 dark:bg-zinc-900/40",
    accent: "before:bg-zinc-400/70 dark:before:bg-zinc-500/70",
  },
};

export const LeadCard = ({ lead }: { lead: Lead }) => {
  if (!lead) return null;
  return <LeadCardContent lead={lead} />;
};

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

  return (
    <div className="cursor-pointer select-none" onClick={handleClick}>
      <RecordContextProvider value={lead}>
        <Card
          className={cn(
            "relative py-3.5 border-0 transition-all duration-200 rounded-xl overflow-hidden",
            "before:absolute before:left-0 before:top-0 before:bottom-0 before:w-1 before:content-['']",
            scoreStyle?.accent,
            scoreStyle?.tint,
            !scoreStyle && "bg-card",
            "shadow-xs hover:-translate-y-0.5 hover:shadow-md",
          )}
        >
          <CardContent className="px-4 py-0 flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <div
                className={`text-sm ${lead.name ? "font-semibold text-foreground" : "italic text-muted-dim font-medium"}`}
              >
                {lead.name ||
                  `Khách hàng chưa biết · đuôi ${(lead.zalo_id || "").slice(-4)}`}
              </div>
              <span className="font-mono text-[10px] font-semibold text-muted-dim shrink-0">
                {lead.updated_at
                  ? new Date(lead.updated_at).toLocaleDateString("vi-VN")
                  : ""}
              </span>
            </div>

            {lead.desired_job && (
              <div className="bg-background/60 rounded-lg px-2.5 py-2 mt-1 text-xs text-muted-foreground/90 font-medium line-clamp-2">
                {lead.desired_job}
              </div>
            )}
          </CardContent>
        </Card>
      </RecordContextProvider>
    </div>
  );
};
