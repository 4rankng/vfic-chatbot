import { type ReactNode, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useDataProvider, useGetIdentity } from "ra-core";
import {
  AlertTriangle,
  Brain,
  History,
  Info,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type {
  BotRunTraceDetail,
  BotRunTraceSummary,
  DecisionTrace,
  DecisionTraceModelTurnEvent,
} from "../types";
import { formatDateTime, outcomeMeta } from "./botRunMeta";
import { modelPhaseLabel, toolNameLabel } from "./decisionTraceMeta";
import {
  clearDecisionTraceQueries,
  DECISION_TRACE_QUERY_KEY,
} from "./decisionTraceQueries";

const TRACE_DISCLAIMER =
  "Hiển thị nội dung suy luận mà nhà cung cấp mô hình trả về cho từng lượt, cùng các công cụ được mô hình chọn.";

const TraceStatus = ({ children }: { children: ReactNode }) => (
  <div
    role="status"
    className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-body text-muted-foreground"
  >
    {children}
  </div>
);

const ModelTurnEventRow = ({
  event,
}: {
  event: DecisionTraceModelTurnEvent;
}) => (
  <li className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3 py-4">
    <span className="flex size-8 items-center justify-center rounded-full bg-primary/10 text-primary">
      <Brain className="size-4" aria-hidden="true" />
    </span>
    <div className="min-w-0 space-y-2 pt-0.5">
      <div>
        <p className="break-words text-body font-semibold text-foreground">
          Lượt suy luận {event.turn}
        </p>
        <p className="mt-0.5 break-words text-helper text-muted-foreground">
          {modelPhaseLabel(event.phase)} · {event.provider} · {event.model}
        </p>
      </div>
      {event.reasoning_status === "not_returned" ? (
        <p className="rounded-md border border-dashed px-3 py-2 text-helper text-muted-foreground">
          Nhà cung cấp không trả về nội dung suy luận cho lượt này.
        </p>
      ) : (
        <div className="rounded-md border bg-muted/40 p-3">
          <p className="mb-1 text-caption font-semibold uppercase tracking-wide text-muted-foreground">
            Thinking
            {event.reasoning_status === "truncated" ? " · đã rút gọn" : ""}
          </p>
          <p className="whitespace-pre-wrap break-words text-body leading-6 text-foreground">
            {event.reasoning}
          </p>
        </div>
      )}
      {event.tool_names.length > 0 ? (
        <div>
          <p className="mb-1 text-caption font-semibold uppercase tracking-wide text-muted-foreground">
            Công cụ được chọn
          </p>
          <div className="flex flex-wrap gap-1.5">
            {event.tool_names.map((name, index) => (
              <span
                key={`${name}-${index}`}
                className="rounded-full border bg-background px-2 py-1 text-helper text-foreground"
              >
                {toolNameLabel(name)}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  </li>
);

export const DecisionTraceRenderer = ({
  trace,
}: {
  trace: DecisionTrace | null;
}) => {
  if (!trace) {
    return <TraceStatus>Không có dấu vết cho lần chạy cũ này.</TraceStatus>;
  }
  if (trace.version !== 1 && trace.version !== 2) {
    return (
      <TraceStatus>
        Phiên bản dấu vết này chưa được hỗ trợ. Không có dữ liệu thô nào được
        hiển thị.
      </TraceStatus>
    );
  }
  const modelTurns =
    trace.version === 2
      ? trace.events.filter(
          (event): event is DecisionTraceModelTurnEvent =>
            event.kind === "model_turn",
        )
      : [];

  return (
    <div className="space-y-3">
      {trace.truncated ? (
        <div
          role="status"
          className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-body text-foreground"
        >
          <AlertTriangle
            className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400"
            aria-hidden="true"
          />
          Dấu vết đã đạt giới hạn lưu trữ. Danh sách dưới đây có thể chưa đầy
          đủ.
        </div>
      ) : null}
      {modelTurns.length === 0 ? (
        <TraceStatus>
          Lần chạy này không có dữ liệu suy luận do nhà cung cấp trả về.
        </TraceStatus>
      ) : (
        <ol
          className="divide-y divide-border"
          aria-label="Các quyết định đã ghi nhận"
        >
          {modelTurns.map((event) => (
            <ModelTurnEventRow
              key={`${event.seq}-${event.kind}`}
              event={event}
            />
          ))}
        </ol>
      )}
    </div>
  );
};

const BotRunTraceDetailContent = ({
  identityId,
  run,
  expanded,
}: {
  identityId: string;
  run: BotRunTraceSummary;
  expanded: boolean;
}) => {
  const dataProvider = useDataProvider<CrmDataProvider>();
  const detailQuery = useQuery<BotRunTraceDetail>({
    queryKey: [...DECISION_TRACE_QUERY_KEY, identityId, "run", run.id],
    queryFn: () => dataProvider.getBotRunTrace(run.id),
    enabled: expanded && run.trace_available,
    gcTime: 0,
    staleTime: 0,
    retry: false,
  });

  if (!run.trace_available) {
    return <DecisionTraceRenderer trace={null} />;
  }
  if (detailQuery.isPending) {
    return (
      <TraceStatus>
        <span className="inline-flex items-center gap-2">
          <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          Đang tải dấu vết…
        </span>
      </TraceStatus>
    );
  }
  if (detailQuery.isError) {
    return (
      <TraceStatus>
        <p>Chưa tải được dấu vết. Hãy thử lại.</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3 min-h-11"
          onClick={() => void detailQuery.refetch()}
        >
          <RefreshCw className="size-4" aria-hidden="true" />
          Thử lại
        </Button>
      </TraceStatus>
    );
  }
  return (
    <DecisionTraceRenderer trace={detailQuery.data?.decision_trace ?? null} />
  );
};

const RunSummary = ({ run }: { run: BotRunTraceSummary }) => {
  const meta = outcomeMeta(run.outcome);
  return (
    <div className="min-w-0 flex-1 pr-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-body font-semibold text-foreground">
          Lần chạy #{run.id}
        </span>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-badge font-semibold uppercase tracking-wide",
            meta.classes,
          )}
        >
          {meta.label}
        </span>
      </div>
      <p className="mt-1 text-helper tabular-nums text-muted-foreground">
        {formatDateTime(run.started_at)}
      </p>
    </div>
  );
};

export const DecisionTracePanel = ({
  conversationId,
  className,
}: {
  conversationId: string;
  className?: string;
}) => {
  const [open, setOpen] = useState(false);
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null);
  const hasOpenedRef = useRef(false);
  const dataProvider = useDataProvider<CrmDataProvider>();
  const queryClient = useQueryClient();
  const { identity } = useGetIdentity();
  const identityId = identity?.id ? String(identity.id) : "";
  const summariesQuery = useQuery({
    queryKey: [
      ...DECISION_TRACE_QUERY_KEY,
      identityId,
      "conversation",
      conversationId,
    ],
    queryFn: () => dataProvider.getConversationBotRuns(conversationId),
    enabled: open && Boolean(identityId) && Boolean(conversationId),
    gcTime: 0,
    staleTime: 0,
    retry: false,
  });

  useEffect(() => {
    if (open) {
      hasOpenedRef.current = true;
      return;
    }
    if (hasOpenedRef.current) clearDecisionTraceQueries(queryClient);
  }, [open, queryClient]);

  useEffect(() => () => clearDecisionTraceQueries(queryClient), [queryClient]);

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setExpandedRunId(null);
    }
  };

  const runs = summariesQuery.data?.data ?? [];

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetTrigger asChild>
        <button
          type="button"
          className={cn("icon-btn ghost", className)}
          aria-label="Agent Thinking"
          title="Agent Thinking"
          aria-expanded={open}
          aria-controls="decision-trace-sheet"
        >
          <History className="icon" aria-hidden="true" />
          <span className="hidden xl:inline">Agent Thinking</span>
        </button>
      </SheetTrigger>
      <SheetContent
        id="decision-trace-sheet"
        side="right"
        className="w-full gap-0 overflow-hidden p-0 sm:max-w-lg"
      >
        <SheetHeader className="border-b px-5 py-4 pr-14">
          <SheetTitle>Agent Thinking</SheetTitle>
          <SheetDescription>
            10 lần chạy chatbot gần nhất của cuộc trò chuyện này.
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 overscroll-contain overflow-y-auto px-5 py-4">
          <div className="mb-4 flex gap-2 rounded-lg bg-muted/60 p-3 text-helper leading-5 text-muted-foreground">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p>{TRACE_DISCLAIMER}</p>
          </div>

          {summariesQuery.isPending ? (
            <TraceStatus>
              <span className="inline-flex items-center gap-2">
                <LoaderCircle
                  className="size-4 animate-spin"
                  aria-hidden="true"
                />
                Đang tải các lần chạy…
              </span>
            </TraceStatus>
          ) : summariesQuery.isError ? (
            <TraceStatus>
              <p>
                Chưa tải được các lần chạy. Hãy kiểm tra kết nối và thử lại.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-3 min-h-11"
                onClick={() => void summariesQuery.refetch()}
              >
                <RefreshCw className="size-4" aria-hidden="true" />
                Thử lại
              </Button>
            </TraceStatus>
          ) : runs.length === 0 ? (
            <TraceStatus>Chưa có lần chạy chatbot nào để hiển thị.</TraceStatus>
          ) : (
            <Accordion
              type="single"
              collapsible
              value={expandedRunId === null ? "" : String(expandedRunId)}
              onValueChange={(value) =>
                setExpandedRunId(value ? Number(value) : null)
              }
              className="border-y border-border"
            >
              {runs.map((run) => (
                <AccordionItem key={run.id} value={String(run.id)}>
                  <AccordionTrigger
                    className="min-h-14 py-3 hover:no-underline"
                    aria-controls={`decision-trace-run-${run.id}`}
                  >
                    <RunSummary run={run} />
                  </AccordionTrigger>
                  <AccordionContent
                    id={`decision-trace-run-${run.id}`}
                    className="pb-4"
                  >
                    <BotRunTraceDetailContent
                      identityId={identityId}
                      run={run}
                      expanded={expandedRunId === run.id}
                    />
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
};

export const DecisionTraceAction = ({
  permissions,
  conversationId,
}: {
  permissions: unknown;
  conversationId: string;
}) =>
  permissions === "admin" ? (
    <DecisionTracePanel conversationId={conversationId} />
  ) : null;
