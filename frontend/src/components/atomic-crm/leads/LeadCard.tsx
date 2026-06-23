import { useRedirect, RecordContextProvider } from "ra-core";

import { LEAD_STAGES, type Lead } from "../types";
import { getRelativeTimeString } from "./leadUtils";
import { LeadAvatar } from "./LeadAvatar";
import { LeadStageMenu } from "./LeadStageMenu";

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
  const isHighPriority = lead.lead_score === "hot";

  const identifier = lead.phone || lead.zalo_id || "";
  const maskedId = identifier.length > 4 ? `•••• ${identifier.slice(-4)}` : identifier;

  return (
    <div className="cursor-pointer select-none bg-card hover:bg-accent/50 transition-colors" onClick={handleClick}>
      <RecordContextProvider value={lead}>
        <div className="flex items-center gap-4 px-4 py-3 min-h-[64px]">
          <LeadAvatar record={lead} size="sm" className="size-10 shrink-0" />

          <div className="min-w-0 flex-[2]">
            <div className="flex items-center gap-2">
              {isHighPriority && (
                <span className="shrink-0 rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-bold text-rose-700 uppercase tracking-wide">
                  Ưu tiên cao
                </span>
              )}
              <div className="truncate text-[15px] font-semibold text-foreground">
                {lead.name || "Chưa rõ tên"}
              </div>
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

          <div className="flex shrink-0 items-center gap-2">
            <LeadStageMenu />
          </div>
        </div>
      </RecordContextProvider>
    </div>
  );
};
