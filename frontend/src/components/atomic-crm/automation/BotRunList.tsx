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
      className="flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/60 focus-visible:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <span
        className={cn(
          "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-badge font-semibold uppercase tracking-wide",
          meta.classes,
        )}
      >
        {meta.label}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-body">{preview}</p>
        <p className="mt-0.5 text-helper text-muted-foreground">
          <span className="font-mono text-[0.7rem] text-foreground/60">
            #{run.id}
          </span>
          <span aria-hidden="true"> · </span>
          {relativeTime}
          {dur ? ` · ${dur}` : ""}
        </p>
      </div>
      <ChevronRight
        className="size-4 shrink-0 text-muted-foreground"
        aria-hidden="true"
      />
    </button>
  );
};

export const BotRunListContent = () => {
  const { data, isPending } = useListContext<BotRun>();

  return (
    <PageShell>
      <PageHeading
        eyebrow="Vận hành"
        title="Lần chạy bot"
        subtitle="Kiểm tra kết quả và thời gian xử lý."
      />
      <section
        className="mt-4 border-y border-[var(--tt-border)] bg-[var(--tt-surface-lift)]"
        aria-labelledby="bot-run-list-title"
      >
        <header className="border-b border-[var(--tt-border)] px-4 py-3">
          <h2
            id="bot-run-list-title"
            className="text-section-title font-semibold text-foreground"
          >
            Nhật ký xử lý
          </h2>
        </header>
        {isPending ? (
          <div className="flex flex-col" role="status" aria-label="Đang tải">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="flex min-h-14 items-start gap-3 border-b p-4"
              >
                <Skeleton className="h-5 w-24" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3.5 w-3/4" />
                  <Skeleton className="h-3 w-1/3" />
                </div>
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
