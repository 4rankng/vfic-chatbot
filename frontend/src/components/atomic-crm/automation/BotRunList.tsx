import { useState } from "react";
import { ListBase, useListContext, useNotify, useRedirect } from "ra-core";
import { ChevronRight, Inbox, RefreshCw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/base/buttons/button";
import { cn, getRelativeTimeString } from "@/lib/utils";
import { EmptyState, ListPagination, PageHeading, PageShell } from "../kit";
import type { BotRun } from "../types";
import { durationLabel, outcomeMeta } from "./botRunMeta";
import "./bot-runs.css";

export const BotRunRow = ({ run }: { run: BotRun }) => {
  const redirect = useRedirect();
  const meta = outcomeMeta(run.outcome);
  const preview = run.proposed_reply?.trim() || "Không có câu trả lời";
  const dur = durationLabel(run);
  const relativeTime = getRelativeTimeString(run.started_at);

  return (
    <button
      type="button"
      data-allow-tall
      onClick={() => redirect("show", "bot_runs", run.id)}
      aria-label={`Xem lần chạy #${run.id}: ${meta.label}, ${relativeTime}${dur ? `, ${dur}` : ""}`}
      className="bot-run-row group flex min-h-16 min-w-0 flex-1 items-center gap-3 px-4 py-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-5"
    >
      <div className="min-w-0 flex-1">
        <p className="bot-run-preview text-body font-medium text-foreground">
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
          <span className="font-mono text-[0.7rem] text-foreground/70">
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

/**
 * Tailkit `a-c-timeline-01` vertical rail, at console density: a hairline guide
 * with one marker per run, capped at both ends so the line does not run into the
 * section border. The marker carries the run's outcome colour (`meta.indicatorClasses`
 * sets `currentColor`, the marker paints with `bg-current`), so the audit trail
 * reads chronologically and by outcome at a glance.
 */
const BotRunTimelineRail = ({
  outcome,
  isFirst,
  isLast,
}: {
  outcome: BotRun["outcome"];
  isFirst: boolean;
  isLast: boolean;
}) => {
  const meta = outcomeMeta(outcome);

  return (
    <span
      aria-hidden="true"
      className="ml-4 flex w-4 shrink-0 flex-col items-center sm:ml-5"
    >
      <span
        className={cn(
          "w-px flex-1",
          isFirst ? "bg-transparent" : "bg-[var(--workspace-border)]",
        )}
      />
      <span
        className={cn(
          "my-1.5 size-2.5 shrink-0 rounded-full bg-current",
          meta.indicatorClasses,
        )}
      />
      <span
        className={cn(
          "w-px flex-1",
          isLast ? "bg-transparent" : "bg-[var(--workspace-border)]",
        )}
      />
    </span>
  );
};

const SkeletonRows = () => (
  <div className="flex flex-col" role="status" aria-label="Đang tải">
    {Array.from({ length: 8 }).map((_, index) => (
      <div
        key={index}
        className="flex min-h-16 items-center gap-3 border-b border-[var(--workspace-border)] px-4 py-3 sm:px-5"
      >
        <span className="flex-1 space-y-2">
          <span className="block h-4 w-3/4 animate-pulse rounded bg-[var(--workspace-surface-muted)]" />
          <span className="block h-3 w-2/5 animate-pulse rounded bg-[var(--workspace-surface-muted)]" />
        </span>
        <span className="size-4 shrink-0 animate-pulse rounded bg-[var(--workspace-surface-muted)]" />
      </div>
    ))}
  </div>
);

export const BotRunListContent = () => {
  const { data, total, isPending, isFetching, error, refetch } =
    useListContext<BotRun>();
  const notify = useNotify();
  const [retrying, setRetrying] = useState(false);
  const records = data ?? [];
  const busy = Boolean(isPending || isFetching || retrying);
  const retry = async () => {
    setRetrying(true);
    try {
      const result = await refetch();
      if (result && "error" in result && result.error) {
        notify("Vẫn chưa tải được nhật ký. Vui lòng thử lại.", {
          type: "error",
        });
      }
    } catch {
      notify("Vẫn chưa tải được nhật ký. Vui lòng thử lại.", { type: "error" });
    } finally {
      setRetrying(false);
    }
  };
  const retryAction = (
    <Button
      type="button"
      className="uu-scope"
      color="secondary"
      size="md"
      iconLeading={RefreshCw}
      isLoading={Boolean(isFetching || retrying)}
      onClick={() => void retry()}
    >
      Thử lại
    </Button>
  );

  return (
    <PageShell size="wide" className="bot-runs-workspace">
      <PageHeading
        className="uu-scope"
        eyebrow="Vận hành"
        title="Lần chạy bot"
        subtitle="Theo dõi câu trả lời, kết quả gửi và các bước xử lý."
        actions={
          <Button
            type="button"
            className="uu-scope"
            color="secondary"
            size="sm"
            iconLeading={RefreshCw}
            isDisabled={busy}
            isLoading={Boolean(isFetching || retrying)}
            showTextWhileLoading
            onClick={() => void retry()}
          >
            Cập nhật
          </Button>
        }
      />
      <section
        className="bot-run-list-panel"
        aria-label="Nhật ký xử lý"
        aria-busy={busy}
      >
        <header className="bot-run-list-heading">
          <h2>Nhật ký xử lý</h2>
          <span className="tabular-nums">
            {isPending && total == null
              ? "Đang tải…"
              : `${new Intl.NumberFormat("vi-VN").format(total ?? records.length)} lượt`}
          </span>
        </header>
        {isPending && records.length === 0 ? (
          <SkeletonRows />
        ) : records.length === 0 && error ? (
          <EmptyState
            role="alert"
            className="max-w-none"
            icon={<TriangleAlert aria-hidden="true" />}
            title="Chưa tải được nhật ký"
            description="Hãy kiểm tra kết nối và thử lại."
            action={retryAction}
          />
        ) : records.length === 0 ? (
          <EmptyState
            className="max-w-none"
            icon={<Inbox className="size-6" aria-hidden="true" />}
            title="Chưa có lần chạy bot nào"
            description="Nhật ký sẽ xuất hiện sau lần xử lý đầu tiên."
          />
        ) : (
          <>
            {error && (
              <div
                role="alert"
                className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--workspace-border)] px-4 py-3 text-body"
              >
                <span>
                  Chưa cập nhật được nhật ký. Dữ liệu đã tải vẫn được giữ lại.
                </span>
                {retryAction}
              </div>
            )}
            <div role="list">
              {records.map((run, index) => (
                <div
                  role="listitem"
                  key={run.id}
                  className="flex border-b border-[var(--workspace-border)] last:border-b-0 hover:bg-muted/50 focus-within:bg-muted"
                >
                  <BotRunTimelineRail
                    outcome={run.outcome}
                    isFirst={index === 0}
                    isLast={index === records.length - 1}
                  />
                  <BotRunRow run={run} />
                </div>
              ))}
            </div>
          </>
        )}
      </section>
      <ListPagination
        rowsPerPageOptions={[10, 25, 50, 100]}
        className="justify-center"
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
