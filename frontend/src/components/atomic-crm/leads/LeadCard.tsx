import { useRedirect, RecordContextProvider } from "ra-core";
import { Phone } from "lucide-react";

import { LEAD_STAGES, LEAD_SCORES, type Lead } from "../types";
import { getRelativeTimeString, telHref } from "./leadUtils";
import { LeadAvatar } from "./LeadAvatar";
import { LeadStageMenu } from "./LeadStageMenu";
import {
  TagStack,
  type TagStackTag,
  type TagTone,
} from "@/components/ui/tag-stack";

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

export const LeadCard = ({ lead, showStageBadge, onClick }: { lead: Lead; showStageBadge?: boolean; onClick?: (lead: Lead) => void }) => {
  if (!lead) return null;
  return <LeadCardContent lead={lead} showStageBadge={showStageBadge} onClick={onClick} />;
};

export const LeadCardContent = ({ lead, showStageBadge, onClick }: { lead: Lead; showStageBadge?: boolean; onClick?: (lead: Lead) => void }) => {
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

  const stageLabel = LEAD_STAGES.find((s) => s.value === lead.lead_stage)?.label || lead.lead_stage;

  const identifier = lead.phone || lead.zalo_id || "";
  const maskedId = identifier.length > 4 ? `•••• ${identifier.slice(-4)}` : identifier;

  // Derived tag stack from existing lead signals (no tags backend needed).
  // Score + region/living_area — these aren't surfaced elsewhere in the row, so
  // the pills add info without duplicating the job/stage columns.
  const areaTag = lead.region?.trim() || lead.living_area?.trim() || null;
  const tags: TagStackTag[] = [
    scoreToTag(lead.lead_score),
    areaTag ? { label: areaTag, tone: "default" } : null,
  ].filter((t): t is TagStackTag => t !== null);

  const callHref = telHref(lead.phone);

  return (
    // `group` is required: LeadStageMenu's trigger relies on group-hover to
    // reveal (previously broken — the wrapper had no group ancestor).
    <div className="group cursor-pointer select-none bg-card hover:bg-accent/50 transition-colors" onClick={handleClick}>
      <RecordContextProvider value={lead}>
        <div className="flex items-center gap-4 px-4 py-3 min-h-[64px]">
          <LeadAvatar record={lead} size="sm" className="size-10 shrink-0" />

          <div className="min-w-0 flex-[2]">
            <div className="truncate text-[15px] font-semibold text-foreground">
              {lead.name || "Chưa rõ tên"}
            </div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[13px] text-muted-foreground">
              {!lead.name && (
                <>
                  <span className="shrink-0">SĐT {maskedId}</span>
                  <span className="shrink-0 text-muted-foreground/50">·</span>
                </>
              )}
              <span className="truncate">Nguồn Zalo</span>
            </div>
            {tags.length > 0 && (
              <div className="mt-1.5">
                <TagStack tags={tags} max={2} />
              </div>
            )}
          </div>

          <div className="min-w-0 flex-[2] hidden md:block">
             <div className="truncate text-[14px] text-foreground font-medium">
              {lead.desired_job || "Chưa rõ công việc"}
             </div>
             {showStageBadge && (
               <div className="mt-0.5 text-[13px] text-muted-foreground">
                 Giai đoạn: {stageLabel}
               </div>
             )}
          </div>

          <div className="min-w-0 flex-[2] hidden lg:block text-[13px]">
             <div className="text-muted-foreground">
               Liên hệ cuối: {updatedAt || "Chưa rõ"}
             </div>
             <div className="mt-0.5 text-foreground font-medium">
               Tiếp theo: Gọi lại hôm nay
             </div>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            {callHref && (
              <a
                href={callHref}
                onClick={(e) => e.stopPropagation()}
                aria-label={`Gọi ${lead.phone}`}
                className="flex size-8 items-center justify-center rounded-md border border-border text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
              >
                <Phone className="size-4" />
              </a>
            )}
            <LeadStageMenu />
          </div>
        </div>
      </RecordContextProvider>
    </div>
  );
};
