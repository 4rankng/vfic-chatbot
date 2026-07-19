import { ListBase, useListContext, useRedirect } from "ra-core";
import { Skeleton } from "@/components/ui/skeleton";
import { ListPagination } from "@/components/admin/list-pagination";
import { Inbox } from "lucide-react";
import { cn, getRelativeTimeString } from "@/lib/utils";
import { AlternateCard, EmptyState, PageHeading, PageShell } from "../kit";
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
          "mt-0.5 inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-badge font-semibold uppercase tracking-wide",
          meta.classes,
        )}
      >
        {meta.label}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-body">{preview}</p>
        <p className="mt-0.5 text-helper text-muted-foreground">
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
    <PageShell>
      <PageHeading
        eyebrow="Kiểm tra vận hành"
        title="Lần chạy bot"
        subtitle="Theo dõi kết quả, thời lượng và dấu vết quyết định của từng lượt xử lý."
      />
      <AlternateCard
        className="mt-4"
        title="Nhật ký gần đây"
        description="Mở một dòng để xem Agent Thinking và công cụ đã sử dụng."
        bodyClassName="overflow-hidden"
      >
        <div className="flex min-h-[360px] flex-col overflow-hidden rounded-[inherit] md:h-[min(620px,calc(100dvh-170px))] lg:h-[calc(100vh-190px)]">
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
            <EmptyState
              icon={<Inbox className="size-6" aria-hidden="true" />}
              title="Chưa có lần chạy bot nào"
              description="Các lần thực thi chatbot tuyển dụng sẽ hiển thị tại đây."
              className="flex-1"
            />
          ) : (
            <div className="flex-1 overflow-y-auto">
              {data.map((run) => (
                <BotRunRow key={run.id} run={run} />
              ))}
            </div>
          )}
        </div>
      </AlternateCard>
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
