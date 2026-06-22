import { ListBase, useListContext, useRedirect } from "ra-core";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/utils";
import { TopToolbar } from "../layout/TopToolbar";
import { getRelativeTimeString } from "../leads/leadUtils";
import type { BotRun } from "../types";
import { durationLabel, outcomeMeta } from "./botRunMeta";

const BotRunRow = ({ run }: { run: BotRun }) => {
  const redirect = useRedirect();
  const meta = outcomeMeta(run.outcome);
  const preview =
    run.proposed_reply?.slice(0, 140) ?? "— không có câu trả lời —";
  const dur = durationLabel(run);
  return (
    <button
      type="button"
      onClick={() => redirect("show", "bot_runs", run.id)}
      className="flex w-full items-start gap-3 border-b px-4 py-3 text-left transition-colors hover:bg-muted/60 focus-visible:bg-muted focus-visible:outline-none"
    >
      <span
        className={cn(
          "mt-0.5 inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
          meta.classes,
        )}
      >
        {meta.label}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm">{preview}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {getRelativeTimeString(run.started_at)}
          {dur ? ` · ${dur}` : ""}
        </p>
      </div>
    </button>
  );
};

const BotRunListContent = () => {
  const { data, isPending } = useListContext<BotRun>();

  return (
    <>
      <TopToolbar>
        <h2 className="font-display text-4xl font-extrabold tracking-wide uppercase text-foreground mr-auto">
          Lần chạy bot
        </h2>
      </TopToolbar>
      <Card className="mt-4 overflow-hidden p-0 py-0">
        <div className="flex h-[calc(100vh-220px)] min-h-[400px] flex-col rounded-[inherit] overflow-hidden">
          {isPending ? (
            <div className="flex flex-col">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="flex items-start gap-3 border-b p-4">
                  <Skeleton className="h-5 w-24" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3.5 w-3/4" />
                    <Skeleton className="h-3 w-1/3" />
                  </div>
                </div>
              ))}
            </div>
          ) : !data || data.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
              <Inbox className="size-10 opacity-50" />
              <p className="text-sm font-medium">Chưa có lần chạy bot nào</p>
              <p className="text-xs">
                Các lần thực thi chatbot tuyển dụng sẽ hiển thị tại đây.
              </p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              {data.map((run) => (
                <BotRunRow key={run.id} run={run} />
              ))}
            </div>
          )}
        </div>
      </Card>
    </>
  );
};

// ListBase provides the ListContext; the consumer that calls useListContext
// must be a child of ListBase, not a sibling rendered alongside it.
export const BotRunList = () => (
  <ListBase perPage={100} sort={{ field: "started_at", order: "DESC" }}>
    <BotRunListContent />
  </ListBase>
);
