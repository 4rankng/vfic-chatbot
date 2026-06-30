import { memo } from "react";
import { useRedirect, RecordContextProvider } from "ra-core";

import { LEAD_STAGES, LEAD_SCORES, type Lead } from "../types";
import { getRelativeTimeString } from "./leadUtils";
import { LeadAvatar } from "./LeadAvatar";
import { LeadStageMenu } from "./LeadStageMenu";
import {
  TagStack,
  type TagStackTag,
  type TagTone,
} from "@/components/ui/tag-stack";
import { cn } from "@/lib/utils";

// Derive a compact tag from the categorical lead score (hot/warm/not_interested).
const scoreToTag = (score: Lead["lead_score"]): TagStackTag | null => {
  const found = LEAD_SCORES.find((s) => s.value === score);
  if (!found) return null;
  const tone: TagTone =
    found.value === "hot"
      ? "destructive"
      : found.value === "warm"
        ? "warning"
        : "default";
  return { label: found.label, tone };
};

const compactIdentifier = (lead: Lead) => {
  const identifier = lead.phone || lead.zalo_id || "";
  if (!identifier) return "";
  return identifier.length > 4 ? identifier.slice(-4) : identifier;
};

const displayName = (lead: Lead) => {
  const name = lead.name?.trim();
  if (name) return name;
  const suffix = compactIdentifier(lead);
  return suffix ? `Ứng viên Zalo ${suffix}` : "Ứng viên chưa định danh";
};

const clean = (value?: string | null) => value?.trim() || "";

interface LeadCardProps {
  lead: Lead;
  showStageBadge?: boolean;
  onClick?: (lead: Lead) => void;
}

// Memoize the heavy inner component so it only re-renders when its own props
// change. The list passes a stable onClick (useCallback in LeadListContent)
// and a boolean showStageBadge, so the only driver of re-renders is the lead
// object reference itself — exactly what we want.
const LeadCardContentBase = ({
  lead,
  showStageBadge,
  onClick,
}: LeadCardProps) => {
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

  const updatedAt = lead.updated_at
    ? getRelativeTimeString(lead.updated_at, "vi")
    : null;

  const stageLabel =
    LEAD_STAGES.find((s) => s.value === lead.lead_stage)?.label ||
    lead.lead_stage;

  const identifierSuffix = compactIdentifier(lead);
  const phone = clean(lead.phone);
  const jobLabel = clean(lead.desired_job) || "Cần bổ sung vị trí";
  const salaryLabel = clean(lead.expected_salary) || "Chưa rõ lương";
  const areaLabel = clean(lead.region) || clean(lead.living_area);
  const notes = clean(lead.notes);
  const contactLabel = phone
    ? phone
    : identifierSuffix
      ? `Zalo ${identifierSuffix}`
      : "Chưa có liên hệ";
  const activityLabel = updatedAt ? `Cập nhật ${updatedAt}` : "Chưa có hoạt động";

  // Derived tag stack from existing lead signals (no tags backend needed).
  const tags: TagStackTag[] = [
    scoreToTag(lead.lead_score),
    showStageBadge && stageLabel ? { label: stageLabel, tone: "default" } : null,
    areaLabel ? { label: areaLabel, tone: "default" } : null,
  ].filter((t): t is TagStackTag => t !== null);
  const priorityClass =
    lead.lead_score === "hot"
      ? "lead-card-priority lead-card-priority-hot border-rose-300/80 bg-rose-50/45 hover:border-rose-400/80 hover:bg-rose-50/70 dark:border-rose-500/45 dark:bg-rose-950/20 dark:hover:border-rose-400/65"
      : lead.lead_score === "warm"
        ? "lead-card-priority lead-card-priority-warm border-amber-300/80 bg-amber-50/45 hover:border-amber-400/80 hover:bg-amber-50/70 dark:border-amber-500/45 dark:bg-amber-950/20 dark:hover:border-amber-400/65"
        : "";

  return (
    <article
      className={cn(
        "group w-full max-w-full cursor-pointer select-none overflow-hidden rounded-xl border border-border/70 bg-card p-4 shadow-sm transition-colors hover:border-primary/30 hover:bg-accent/25",
        priorityClass,
      )}
      onClick={handleClick}
    >
      <RecordContextProvider value={lead}>
        <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3">
          <LeadAvatar record={lead} size="sm" className="size-11 shrink-0" />

          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-start justify-between gap-2">
              <div className="min-w-0">
                <h3 className="truncate text-[15px] font-semibold leading-5 text-foreground">
                  {displayName(lead)}
                </h3>
                <p className="mt-0.5 truncate text-[13px] text-muted-foreground">
                  Nguồn Zalo {identifierSuffix ? `· ${identifierSuffix}` : ""}
                </p>
              </div>
            </div>
            {tags.length > 0 && (
              <div className="mt-2">
                <TagStack tags={tags} max={3} />
              </div>
            )}
          </div>

          <div className="-mr-1 -mt-1 flex shrink-0 items-start">
            <LeadStageMenu />
          </div>
        </div>

        <div className="mt-4 divide-y divide-border/70 border-y border-border/70 sm:grid sm:grid-cols-2 sm:gap-2 sm:divide-y-0 sm:border-y-0">
          <Fact label="Vị trí" value={jobLabel} strong />
          <Fact label="Lương" value={salaryLabel} />
          <Fact label="Khu vực" value={areaLabel || "Chưa rõ khu vực"} />
          <Fact label="Liên hệ" value={contactLabel} />
        </div>

        {notes && (
          <p className="mt-3 line-clamp-2 border-l-2 border-border pl-3 text-xs leading-5 text-muted-foreground">
            {notes}
          </p>
        )}

        <div className="mt-3 flex items-center justify-between gap-3 border-t border-border/70 pt-3 text-xs text-muted-foreground">
          <span>{activityLabel}</span>
          {showStageBadge && <span className="font-medium">{stageLabel}</span>}
        </div>
      </RecordContextProvider>
    </article>
  );
};

const Fact = ({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) => (
  <div className="grid min-w-0 grid-cols-[5rem_minmax(0,1fr)] items-baseline gap-3 py-2 sm:block sm:rounded-lg sm:bg-muted/55 sm:px-3 sm:py-2">
    <div className="text-[11px] font-medium text-muted-foreground">
      {label}
    </div>
    <div
      className={`min-w-0 text-right text-[13px] sm:mt-0.5 sm:truncate sm:text-left ${
        strong ? "font-semibold text-foreground" : "font-medium text-foreground/85"
      }`}
    >
      {value}
    </div>
  </div>
);

export const LeadCardContent = memo(LeadCardContentBase);

// Thin null-guard wrapper. Also memoized so a stable onClick + unchanged lead
// reference from the list doesn't needlessly re-render the guard layer either.
export const LeadCard = memo(
  ({ lead, showStageBadge, onClick }: LeadCardProps) => {
    if (!lead) return null;
    return (
      <LeadCardContent
        lead={lead}
        showStageBadge={showStageBadge}
        onClick={onClick}
      />
    );
  },
);
