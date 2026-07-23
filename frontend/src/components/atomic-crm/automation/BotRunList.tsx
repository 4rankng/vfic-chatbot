import { ListBase, useListContext, useRedirect } from "ra-core";
import { Skeleton } from "@/components/ui/skeleton";
import { ListPagination } from "@/components/admin/list-pagination";
import { ChevronRight, Inbox } from "lucide-react";
import { cn, getRelativeTimeString } from "@/lib/utils";
import { EmptyState, PageHeading, PageShell } from "../kit";
import type { BotRun } from "../types";
import { durationLabel, outcomeMeta } from "./botRunMeta";

export const BotRunRow = ({ run }: { run: BotRun }) => {
  const redirect = useRedirect();
  const meta = outcomeMeta(run.outcome);
  const preview =
    run.proposed_reply?.slice(0, 140) ?? "— không có câu trả lời —";
  const dur = durationLabel(run);
  const relativeTime = getRelativeTimeString(run.started_at);

  return (
    <button
      type="button"
      onClick={() => redirect("show", "bot_runs", run.id)}
      aria-label={`Xem lần chạy #${run.id}: ${meta.label}, ${relativeTime}${dur ? `, ${dur}` : ""}`}
      className="group flex min-h-16 w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/50 focus-visible:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-5"
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-body font-medium text-foreground">
          {preview}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-helper text-muted-foreground">
          <span
            data-slot="bot-run-outcome"
            className={cn(
              "inline-flex items-center gap-1 font-medium",
              meta.indicatorClasses,
            )}
          >
            <span
              className="size-1.5 rounded-full bg-current"
              aria-hidden="true"
            />
            {meta.label}
          </span>
          <span aria-hidden="true">·</span>
          <span className="font-mono text-[0.7rem] text-foreground/60">
            #{run.id}
          </span>
          <span aria-hidden="true">·</span>
          <span>{relativeTime}</span>
          {dur ? (
            <>
              <span aria-hidden="true">·</span>
              <span>{dur}</span>
            </>
          ) : null}
        </div>
      </div>
      <ChevronRight
        className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
        aria-hidden="true"
      />
    </button>
  );
};

export const BotRunListContent = () => {
  const { data, isPending } = useListContext<BotRun>();

  return (
    <PageShell>
      <PageHeading title="Lần chạy bot" />
      <section
        className="mt-4 border-y border-[var(--tt-border)] bg-[var(--tt-surface-lift)]"
        aria-label="Nhật ký xử lý"
      >
        {isPending ? (
          <div className="flex flex-col" role="status" aria-label="Đang tải">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="flex min-h-16 items-center gap-3 border-b px-4 py-3 sm:px-5"
              >
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-3 w-2/5" />
                </div>
                <Skeleton className="size-4" />
              </div>
            ))}
          </div>
        ) : !data || data.length === 0 ? (
          <EmptyState
            icon={<Inbox className="size-6" aria-hidden="true" />}
            title="Chưa có lần chạy bot nào"
            description="Nhật ký sẽ xuất hiện sau lần xử lý đầu tiên."
          />
        ) : (
          <div role="list">
            {data.map((run) => (
              <div
                role="listitem"
                key={run.id}
                className="border-b border-[var(--tt-border)] last:border-b-0"
              >
                <BotRunRow run={run} />
              </div>
            ))}
          </div>
        )}
      </section>
      <ListPagination
        rowsPerPageOptions={[10, 25, 50, 100]}
        className="mt-3 justify-center"
      />
    </PageShell>
  );
};

// ListBase provides the ListContext; the consumer that calls useListContext
// must be a child of ListBase, not a sibling rendered alongside it.
export const BotRunList = () => (
  <ListBase perPage={25} sort={{ field: "started_at", order: "DESC" }}>
    <BotRunListContent />
  </ListBase>
);
