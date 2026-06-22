import { useEffect, useState, type ReactNode } from "react";
import { useRecordContext, useDataProvider } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Bot,
  Briefcase,
  CircleDollarSign,
  Inbox,
  Phone,
  UserCircle,
  User as UserIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

import type { Conversation, Lead } from "../types";
import type { CrmDataProvider } from "../providers/supabase/dataProvider";
import { LeadStageBadge } from "./LeadStageBadge";
import { LeadScoreBar } from "./LeadScoreBar";
import { LeadAvatar } from "./LeadAvatar";
import { useConversationActions } from "../conversations/useConversationActions";

const Field = ({
  icon,
  label,
  value,
  mono,
  colorClass = "bg-muted border-border text-muted-foreground",
}: {
  icon: ReactNode;
  label: string;
  value?: ReactNode;
  mono?: boolean;
  colorClass?: string;
}) => {
  const empty = value === undefined || value === null || value === "";
  return (
    <div className="flex gap-4">
      <div className={cn("size-8 rounded-full flex items-center justify-center shrink-0 border mt-1", colorClass)}>
        {icon}
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-0.5">
          {label}
        </p>
        <p
          className={cn(
            "text-sm font-medium leading-snug",
            mono && "font-mono",
            empty ? "italic text-muted-foreground font-normal" : "text-foreground",
          )}
        >
          {empty ? "Chưa cung cấp" : value}
        </p>
      </div>
    </div>
  );
};

/**
 * Right-hand lead drawer for the conversation inbox. Resolves the lead for the
 * active conversation via `leads.zalo_id = conversations.zalo_chat_id`, shows
 * the qualification summary, and surfaces Take-over / Release controls.
 */
export const LeadProfilePanel = () => {
  const conversation = useRecordContext<Conversation>();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [lead, setLead] = useState<Lead | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const zaloChatId = conversation?.zalo_chat_id;

  useEffect(() => {
    if (!zaloChatId) {
      setLead(null);
      setNotFound(true);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setNotFound(false);
    (async () => {
      try {
        const { data } = await dataProvider.getList("leads", {
          filter: { zalo_id: zaloChatId },
          pagination: { page: 1, perPage: 1 },
          sort: { field: "updated_at", order: "DESC" },
        });
        if (cancelled) return;
        setLead((data?.[0] as Lead) ?? null);
        setNotFound(!data?.[0]);
      } catch {
        if (cancelled) return;
        setLead(null);
        setNotFound(true);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dataProvider, zaloChatId]);

  const { isBotMode } = useConversationActions(conversation);

  return (
    <Card className="flex h-full flex-col overflow-hidden rounded-none border-0 bg-background shadow-[-4px_0_24px_rgba(0,0,0,0.02)] relative z-10">
      <CardHeader className="h-[72px] px-6 flex flex-row items-center justify-between border-b border-border/40 shrink-0 py-0">
        <CardTitle className="font-semibold text-foreground flex items-center gap-2 text-base">
          <UserIcon className="size-4 text-muted-foreground" />
          Hồ sơ khách hàng
        </CardTitle>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground bg-muted/50 px-2 py-1 rounded-md border border-border/50 font-medium">
          {isBotMode ? (
            <>
              <Bot className="size-3.5" /> Bot
            </>
          ) : (
            <>
              <UserCircle className="size-3.5" /> Nhân viên
            </>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : notFound || !lead ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center text-muted-foreground">
            <div className="rounded-full bg-muted p-3">
              <Inbox className="size-6" />
            </div>
            <p className="text-sm font-medium">Chưa liên kết khách hàng</p>
            <p className="text-xs">
              Cuộc trò chuyện này chưa có khách hàng tương ứng (nối qua
              leads.zalo_id = conversations.zalo_chat_id).
            </p>
          </div>
        ) : (
          <div>
            <div className="flex items-center gap-4 mb-8">
              <LeadAvatar record={lead} size="lg" className="w-14 h-14 text-xl shadow-md" />
              <div>
                <h3 className="font-semibold text-foreground text-lg mb-1">
                  {lead.name ||
                    `Khách hàng chưa biết · ${lead.zalo_id?.slice(-4) || "????"}`}
                </h3>
                <div className="flex flex-wrap items-center gap-1.5">
                  <LeadStageBadge stage={lead.lead_stage} />
                  <LeadScoreBar score={lead.lead_score} />
                </div>
              </div>
            </div>
            <div className="space-y-6">
              <Field
                icon={<Phone className="size-4" />}
                label="Số điện thoại"
                value={lead.phone}
                colorClass="bg-muted text-muted-foreground border-border"
              />
              <Field
                icon={<Briefcase className="size-4 text-blue-500" />}
                label="Công việc mong muốn"
                value={lead.desired_job}
                colorClass="bg-blue-500/10 border-blue-500/20"
              />
              <Field
                icon={<CircleDollarSign className="size-4 text-green-500" />}
                label="Lương mong muốn"
                value={lead.expected_salary}
                colorClass="bg-green-500/10 border-green-500/20"
              />
            </div>
            <div className="mt-10 pt-6 border-t border-border/40">
                <button className="w-full flex items-center justify-center gap-2 bg-card border border-border/50 text-foreground py-2.5 rounded-xl text-sm font-medium hover:bg-muted/50 transition-colors shadow-sm">
                    <UserIcon className="size-4" /> Cập nhật hồ sơ
                </button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
