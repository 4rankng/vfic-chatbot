import { memo } from "react";
import { useRedirect, RecordContextProvider } from "ra-core";

import { type Lead } from "../types";
import { LeadAvatar } from "./LeadAvatar";
import { LeadStageMenu } from "./LeadStageMenu";

const compactIdentifier = (lead: Lead) => {
  const identifier = lead.phone || lead.zalo_id || "";
  if (!identifier) return "";
  return identifier.length > 4 ? identifier.slice(-4) : identifier;
};

const displayName = (lead: Lead) => {
  const name = lead.name?.trim();
  if (name) return name;
  const suffix = compactIdentifier(lead);
  return suffix ? `Ứng viên ${suffix}` : "Ứng viên chưa định danh";
};

interface LeadCardProps {
  lead: Lead;
  onClick?: (lead: Lead) => void;
}

// Memoize the heavy inner component so it only re-renders when its own props
// change. The list passes a stable onClick (useCallback in LeadListContent)
// so the only driver of re-renders is the lead object reference itself.
const LeadCardContentBase = ({ lead, onClick }: LeadCardProps) => {
  const redirect = useRedirect();
  const handleClick = () => {
    if (onClick) {
      onClick(lead);
    } else {
      redirect(`/leads/${lead.id}/show`, undefined, undefined, undefined, {
        _scrollToTop: false,
      });
    }
  };

  const identifierSuffix = compactIdentifier(lead);

  return (
    <article
      className="group w-full max-w-full cursor-pointer select-none overflow-hidden rounded-lg border border-border bg-card px-2.5 py-1.5 shadow-[0_2px_8px_rgba(26,34,40,0.08),0_1px_2px_rgba(26,34,40,0.06)] transition-colors hover:border-primary/35 hover:bg-card hover:shadow-[0_4px_14px_rgba(26,34,40,0.11),0_1px_3px_rgba(26,34,40,0.08)] dark:border-border/80 dark:shadow-[0_2px_10px_rgba(0,0,0,0.28)] dark:hover:border-primary/35 dark:hover:bg-accent/20"
      onClick={handleClick}
    >
      <RecordContextProvider value={lead}>
        <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2">
          <LeadAvatar record={lead} size="sm" className="size-7 shrink-0" />

          <div className="flex min-w-0 items-center gap-1.5">
            <h3 className="truncate text-[13px] font-semibold leading-5 text-foreground">
              {displayName(lead)}
            </h3>
            {identifierSuffix ? (
              <span className="shrink-0 text-[11px] leading-4 text-muted-foreground">
                · {identifierSuffix}
              </span>
            ) : null}
          </div>

          <div className="-mr-1 flex shrink-0 items-center">
            <LeadStageMenu />
          </div>
        </div>
      </RecordContextProvider>
    </article>
  );
};

export const LeadCardContent = memo(LeadCardContentBase);

// Thin null-guard wrapper. Also memoized so a stable onClick + unchanged lead
// reference from the list doesn't needlessly re-render the guard layer either.
export const LeadCard = memo(({ lead, onClick }: LeadCardProps) => {
  if (!lead) return null;
  return <LeadCardContent lead={lead} onClick={onClick} />;
});
