import { ShowBase, useShowContext, useDataProvider } from "ra-core";
import type { ShowBaseProps } from "ra-core";
import { useIsMobile } from "@/hooks/use-mobile";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EditButton } from "@/components/admin/edit-button";
import { RefreshButton } from "@/components/admin/refresh-button";
import { DeleteButton } from "@/components/admin";
import { TopToolbar } from "../layout/TopToolbar";
import { ConversationShowContent } from "../conversations/ConversationShow";
import { RecordContextProvider } from "ra-core";
import { useEffect, useState } from "react";
import type { Lead, Conversation } from "../types";
import { LeadAvatar } from "./LeadAvatar";
import { LeadBreadcrumb } from "./LeadBreadcrumb";
import { LeadInfoPanel } from "./LeadInfoPanel";
import { LeadScoreBar } from "./LeadScoreBar";
import { LeadStageBadge } from "./LeadStageBadge";
import { Bot } from "lucide-react";
import { cn } from "@/lib/utils";

const LeadChat = ({ zaloId }: { zaloId: string }) => {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const dataProvider = useDataProvider<any>();

  useEffect(() => {
    let cancelled = false;
    if (!zaloId) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);

    Promise.resolve(
      dataProvider.getList("conversations", {
        filter: { zalo_chat_id: zaloId },
        pagination: { page: 1, perPage: 1 },
        sort: { field: "updated_at", order: "DESC" },
      }),
    )
      .then(({ data }: { data: Conversation[] }) => {
        if (cancelled) return;
        setConversation(data?.[0] ?? null);
        setIsLoading(false);
      })
      .catch((e: any) => {
        if (cancelled) return;
        const msg = e?.message ?? "Failed to load conversation";
        if (/vfic_chat_histories|relation.*does not exist/i.test(msg)) {
          setConversation(null);
          setError(null);
        } else {
          setError(msg);
        }
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [zaloId, dataProvider]);

  if (isLoading) {
    return (
      <Card className="flex h-[calc(100vh-220px)] flex-col">
        <CardHeader className="border-b">
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent className="flex flex-1 flex-col gap-4 p-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className={cn(
                "flex w-full",
                i % 2 === 0 ? "justify-start" : "justify-end",
              )}
            >
              <Skeleton
                className={cn("h-16 rounded-lg", i % 2 === 0 ? "w-1/2" : "w-2/5")}
              />
            </div>
          ))}
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="flex h-[calc(100vh-220px)] flex-col items-center justify-center p-6">
        <div className="text-center text-sm text-muted-foreground">
          <p className="font-medium text-destructive">
            Failed to load conversation
          </p>
          <p className="mt-1 text-xs">{error}</p>
        </div>
      </Card>
    );
  }

  if (!conversation) {
    return (
      <Card className="flex h-[calc(100vh-220px)] flex-col items-center justify-center p-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="rounded-full bg-muted p-4">
            <Bot className="size-8 text-muted-foreground" />
          </div>
          <div>
            <p className="text-base font-medium">No conversation yet</p>
            <p className="mt-1 max-w-sm text-sm text-muted-foreground">
              When this candidate starts a chat on Zalo, the conversation will
              appear here.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <RecordContextProvider value={conversation}>
      <ConversationShowContent />
    </RecordContextProvider>
  );
};

const LeadHero = () => {
  const { record, isPending } = useShowContext<Lead>();
  if (isPending || !record) return null;

  return (
    <Card>
      <CardContent className="flex flex-col gap-5 p-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4">
          <LeadAvatar size="xl" />
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-bold tracking-tight">
              {record.name || "Unnamed Lead"}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              {record.phone && (
                <a
                  href={`tel:${record.phone.replace(/\s+/g, "")}`}
                  className="inline-flex items-center gap-1 hover:text-foreground"
                >
                  {record.phone}
                </a>
              )}
              {record.desired_job && (
                <span className="inline-flex items-center gap-1">
                  <span className="text-muted-foreground/50">•</span>
                  {record.desired_job}
                </span>
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <LeadStageBadge stage={record.lead_stage} />
              <LeadScoreBar
                score={record.lead_score ?? 0}
                showLabel={false}
                className="w-32"
              />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

export const LeadShowContent = () => {
  const { record, isPending, isLoading } = useShowContext<Lead>();
  if (isPending) {
    return (
      <div className="mt-2 flex flex-col gap-4">
        <Skeleton className="h-32 w-full rounded-xl" />
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <div className="flex flex-col gap-4">
            <Skeleton className="h-64 w-full rounded-xl" />
            <Skeleton className="h-32 w-full rounded-xl" />
          </div>
          <Skeleton className="h-[calc(100vh-220px)] w-full rounded-xl" />
        </div>
      </div>
    );
  }
  if (isLoading || !record) return null;

  return (
    <div className="mt-2 flex flex-col gap-4">
      <LeadHero />
      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <div className="flex flex-col gap-4">
          <LeadInfoPanel />
        </div>
        <div className="flex flex-col">
          <LeadChat zaloId={record.zalo_id} />
        </div>
      </div>
    </div>
  );
};

export const LeadShowContentMobile = () => {
  const { record, isPending, isLoading } = useShowContext<Lead>();
  if (isPending) {
    return (
      <div className="flex flex-col gap-3 p-2">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }
  if (isLoading || !record) return null;

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardContent className="flex flex-col gap-3 p-4">
          <div className="flex items-center gap-3">
            <LeadAvatar size="lg" />
            <div className="min-w-0 flex-1">
              <h1 className="truncate text-lg font-semibold">
                {record.name || "Unnamed Lead"}
              </h1>
              <div className="text-xs text-muted-foreground">
                {record.phone || "No phone"}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <LeadStageBadge stage={record.lead_stage} />
            <LeadScoreBar
              score={record.lead_score ?? 0}
              showLabel={false}
              className="flex-1"
            />
          </div>
          {record.desired_job && (
            <div className="text-sm text-muted-foreground">
              {record.desired_job}
            </div>
          )}
        </CardContent>
      </Card>
      <LeadInfoPanel />
      <LeadChat zaloId={record.zalo_id} />
    </div>
  );
};

export const LeadShow = (props: ShowBaseProps = {}) => {
  const isMobile = useIsMobile();
  return (
    <ShowBase {...props}>
      <div className="flex flex-col gap-3">
        <LeadBreadcrumb />
        <TopToolbar>
          <h2 className="mr-auto text-xl font-semibold">Lead</h2>
          <RefreshButton />
          <EditButton />
          <DeleteButton
            className="h-6 cursor-pointer hover:bg-destructive/10! text-destructive! border-destructive! focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40"
            size="sm"
          />
        </TopToolbar>
        {isMobile ? <LeadShowContentMobile /> : <LeadShowContent />}
      </div>
    </ShowBase>
  );
};
