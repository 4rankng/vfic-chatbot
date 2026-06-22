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
}: {
  icon: ReactNode;
  label: string;
  value?: ReactNode;
  mono?: boolean;
}) => {
  const empty = value === undefined || value === null || value === "";
  return (
    <div className="flex items-start gap-2.5 py-2">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <div
          className={cn(
            "mt-0.5 text-sm",
            mono && "font-mono text-xs",
            empty && "italic text-muted-foreground",
          )}
        >
          {empty ? <span className="text-xs">Not provided</span> : value}
        </div>
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
    <Card className="flex h-full flex-col overflow-hidden rounded-none border-0">
      <CardHeader className="border-b px-4 py-3">
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            <UserIcon className="size-4 text-muted-foreground" />
            Lead Profile
          </span>
          <Badge
            variant={isBotMode ? "secondary" : "default"}
            className="shrink-0 gap-1"
          >
            {isBotMode ? (
              <>
                <Bot className="size-3" /> Bot
              </>
            ) : (
              <>
                <UserCircle className="size-3" /> Human
              </>
            )}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-4">
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
            <p className="text-sm font-medium">No lead linked</p>
            <p className="text-xs">
              This conversation has no matching lead yet (joins on leads.zalo_id
              = conversations.zalo_chat_id).
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <LeadAvatar record={lead} size="md" />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">
                  {lead.name ||
                    `Unknown lead · ending ${lead.zalo_id?.slice(-4) || "????"}`}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <LeadStageBadge stage={lead.lead_stage} />
                  <LeadScoreBar score={lead.lead_score} />
                </div>
              </div>
            </div>
            <Field
              icon={<Phone className="size-3.5" />}
              label="Phone"
              value={lead.phone}
            />
            <Field
              icon={<Briefcase className="size-3.5" />}
              label="Desired job"
              value={lead.desired_job}
            />
            <Field
              icon={<CircleDollarSign className="size-3.5" />}
              label="Expected salary"
              value={lead.expected_salary}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
};
