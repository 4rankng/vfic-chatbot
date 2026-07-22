import { useCallback, useEffect, useRef, useState } from "react";
import { useNotify } from "ra-core";
import { Loader2, Play, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  deleteSinglePageExternalSource,
  deleteExternalSource,
  listSinglePageExternalSources,
  listExternalSources,
  runSinglePageExternalSourceNow,
  runExternalSourceNow,
  singlePageSyncErrorMessage,
  type ExternalSourceSyncState,
  type SinglePageExternalSourceSyncState,
} from "@/lib/vfic/knowledgeService";

const RUN_NOW_COOLDOWN_MS = 5 * 60 * 1000;
const FAST_FOLLOW_UP_REFRESH_MS = 4000;
const SLOW_FOLLOW_UP_REFRESH_MS = 30_000;
const FAST_FOLLOW_UP_POLLS = 30;
const WORKER_ATTEMPTS = 4;
const WORKER_JOB_TIMEOUT_MS = 30 * 60 * 1000;
const WORKER_RETRY_INTERVAL_MS = 2000 * 1000;
export const SINGLE_PAGE_SYNC_MAX_POLL_MS =
  WORKER_ATTEMPTS * WORKER_JOB_TIMEOUT_MS +
  (WORKER_ATTEMPTS - 1) * WORKER_RETRY_INTERVAL_MS;
const FAST_FOLLOW_UP_WINDOW_MS =
  FAST_FOLLOW_UP_POLLS * FAST_FOLLOW_UP_REFRESH_MS;
const MAX_FOLLOW_UP_POLLS =
  FAST_FOLLOW_UP_POLLS +
  Math.ceil(
    (SINGLE_PAGE_SYNC_MAX_POLL_MS - FAST_FOLLOW_UP_WINDOW_MS) /
      SLOW_FOLLOW_UP_REFRESH_MS,
  );

type Props = {
  projectId: string;
  /** Bump to force a re-fetch (parent signals after create/delete in a sibling). */
  refreshSignal?: number;
  onChange?: () => void;
  disabled?: boolean;
  variant?: "category" | "single-page";
  mutable?: boolean;
  onSynchronized?: () => void;
};

type ExternalSourceRow =
  | ExternalSourceSyncState
  | SinglePageExternalSourceSyncState;

type PollSession = {
  baselineById: Map<string, string>;
  targetId?: string;
  attempts: number;
};

const STATUS_LABEL: Record<string, string> = {
  NEW: "Mới",
  OK: "Đã đồng bộ",
  NO_OP: "Không đổi",
  FAILED: "Lỗi",
};

const statusTone = (row: Pick<ExternalSourceRow, "last_status">): string => {
  if (row.last_status === "FAILED") return "text-destructive";
  if (row.last_status === "OK") return "text-primary";
  return "text-muted-foreground";
};

const formatTimestamp = (value?: string | null): string => {
  if (!value) return "—";
  try {
    return new Intl.DateTimeFormat("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
};

const truncate = (url: string, max = 48): string =>
  url.length > max ? `${url.slice(0, max)}…` : url;

const rowProgressSignature = (row: ExternalSourceRow): string =>
  [
    row.last_status,
    row.last_synced_at ?? "",
    row.last_content_hash ?? "",
    row.updated_at,
  ].join(":");

const successfulSyncSignature = (nextRows: ExternalSourceRow[]): string =>
  nextRows
    .filter((row) => row.last_status === "OK" || row.last_status === "NO_OP")
    .map((row) => `${row.id}:${rowProgressSignature(row)}`)
    .join("|");

const isTerminal = (row: ExternalSourceRow): boolean =>
  row.last_status === "OK" ||
  row.last_status === "NO_OP" ||
  row.last_status === "FAILED";

const rowsNeedFollowUp = (nextRows: ExternalSourceRow[]): boolean =>
  nextRows.some(
    (row) => row.last_status === "NEW" || row.last_status === "PROCESSING",
  );

const pollHasCompleted = (
  session: PollSession,
  nextRows: ExternalSourceRow[],
): boolean => {
  const candidates = session.targetId
    ? nextRows.filter((row) => row.id === session.targetId)
    : nextRows;
  return candidates.some(
    (row) =>
      isTerminal(row) &&
      rowProgressSignature(row) !== session.baselineById.get(row.id),
  );
};

/**
 * Read-only list of configured external sources for a project. Auto-sync state
 * is shown but not editable inline (delete + re-create to change it). Each row
 * has a "Process now" button (5-minute cooldown) and a "Remove" button.
 */
export const ExternalSourceList = ({
  projectId,
  refreshSignal,
  onChange,
  disabled,
  variant = "category",
  mutable = true,
  onSynchronized,
}: Props) => {
  const notify = useNotify();
  const [rows, setRows] = useState<ExternalSourceRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [cooldownId, setCooldownId] = useState<string | null>(null);
  const cooldownTimer = useRef<number | null>(null);
  const followUpTimer = useRef<number | null>(null);
  const rowsRef = useRef<ExternalSourceRow[]>([]);
  const syncSignatureRef = useRef<string | null>(null);
  const initializedSyncSignature = useRef(false);
  const pollSessionRef = useRef<PollSession | null>(null);
  const requestGenerationRef = useRef(0);
  const requestControllerRef = useRef<AbortController | null>(null);
  const previousRefreshSignalRef = useRef({ projectId, value: refreshSignal });
  const suppressNextRefreshPollRef = useRef(false);
  const loadRef = useRef<() => Promise<void>>(async () => undefined);
  const onSynchronizedRef = useRef(onSynchronized);
  const isSinglePage = variant === "single-page";

  useEffect(() => {
    onSynchronizedRef.current = onSynchronized;
  }, [onSynchronized]);

  const clearFollowUpTimer = useCallback(() => {
    if (followUpTimer.current !== null) {
      window.clearTimeout(followUpTimer.current);
      followUpTimer.current = null;
    }
  }, []);

  const stopPolling = useCallback(() => {
    pollSessionRef.current = null;
    clearFollowUpTimer();
  }, [clearFollowUpTimer]);

  const beginPolling = useCallback((targetId?: string) => {
    if (pollSessionRef.current) return;
    pollSessionRef.current = {
      baselineById: new Map(
        rowsRef.current.map((row) => [row.id, rowProgressSignature(row)]),
      ),
      targetId,
      attempts: 0,
    };
  }, []);

  const scheduleNextPoll = useCallback(() => {
    const session = pollSessionRef.current;
    clearFollowUpTimer();
    if (!session) return;
    if (session.attempts >= MAX_FOLLOW_UP_POLLS) {
      pollSessionRef.current = null;
      return;
    }
    session.attempts += 1;
    const delay =
      session.attempts <= FAST_FOLLOW_UP_POLLS
        ? FAST_FOLLOW_UP_REFRESH_MS
        : SLOW_FOLLOW_UP_REFRESH_MS;
    followUpTimer.current = window.setTimeout(
      () => void loadRef.current(),
      delay,
    );
  }, [clearFollowUpTimer]);

  const load = useCallback(async () => {
    const requestGeneration = ++requestGenerationRef.current;
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    try {
      const nextRows = isSinglePage
        ? await listSinglePageExternalSources(projectId, controller.signal)
        : await listExternalSources(projectId, controller.signal);
      if (
        controller.signal.aborted ||
        requestGeneration !== requestGenerationRef.current
      ) {
        return;
      }
      rowsRef.current = nextRows;
      setRows(nextRows);

      if (isSinglePage) {
        const nextSignature = successfulSyncSignature(nextRows);
        const successfulSyncChanged =
          initializedSyncSignature.current &&
          Boolean(nextSignature) &&
          nextSignature !== syncSignatureRef.current;
        if (!initializedSyncSignature.current) {
          initializedSyncSignature.current = true;
        }
        syncSignatureRef.current = nextSignature;

        const pollSession = pollSessionRef.current;
        if (pollSession && pollHasCompleted(pollSession, nextRows)) {
          stopPolling();
        } else {
          if (!pollSession && rowsNeedFollowUp(nextRows)) beginPolling();
          if (pollSessionRef.current) scheduleNextPoll();
        }

        if (successfulSyncChanged) onSynchronizedRef.current?.();
      }
    } catch (error) {
      if (
        controller.signal.aborted ||
        requestGeneration !== requestGenerationRef.current
      ) {
        return;
      }
      notify(
        isSinglePage
          ? singlePageSyncErrorMessage(error)
          : (error as Error).message,
        { type: "error" },
      );
      if (pollSessionRef.current) scheduleNextPoll();
    } finally {
      if (requestGeneration === requestGenerationRef.current) setLoading(false);
    }
  }, [
    beginPolling,
    isSinglePage,
    notify,
    projectId,
    scheduleNextPoll,
    stopPolling,
  ]);

  loadRef.current = load;

  useEffect(() => {
    setLoading(true);
    setRows(null);
    rowsRef.current = [];
    syncSignatureRef.current = null;
    initializedSyncSignature.current = false;
    pollSessionRef.current = null;
    setCooldownId(null);
    setProcessingId(null);
    void load();
    return () => {
      requestGenerationRef.current += 1;
      requestControllerRef.current?.abort();
      if (cooldownTimer.current !== null)
        window.clearTimeout(cooldownTimer.current);
      stopPolling();
    };
  }, [isSinglePage, load, projectId, stopPolling]);

  useEffect(() => {
    if (previousRefreshSignalRef.current.projectId !== projectId) {
      previousRefreshSignalRef.current = { projectId, value: refreshSignal };
      return;
    }
    if (refreshSignal === previousRefreshSignalRef.current.value) return;
    previousRefreshSignalRef.current.value = refreshSignal;
    const suppressPoll = suppressNextRefreshPollRef.current;
    suppressNextRefreshPollRef.current = false;
    if (
      isSinglePage &&
      !suppressPoll &&
      rowsRef.current.length === 0 &&
      !pollSessionRef.current
    ) {
      beginPolling();
    }
    void load();
  }, [beginPolling, isSinglePage, load, projectId, refreshSignal]);

  const startCooldown = (id: string) => {
    setCooldownId(id);
    if (cooldownTimer.current !== null)
      window.clearTimeout(cooldownTimer.current);
    cooldownTimer.current = window.setTimeout(
      () => setCooldownId(null),
      RUN_NOW_COOLDOWN_MS,
    );
  };

  const runNow = async (row: ExternalSourceRow) => {
    setProcessingId(row.id);
    try {
      if (isSinglePage) {
        await runSinglePageExternalSourceNow(projectId, row.id);
      } else {
        await runExternalSourceNow(projectId, row.id);
      }
      notify("Đang xử lý nội dung mới. Vui lòng đợi vài giây.", {
        type: "info",
      });
      startCooldown(row.id);
      if (isSinglePage) {
        stopPolling();
        beginPolling(row.id);
        scheduleNextPoll();
      }
    } catch (error) {
      const status = (error as { status?: number }).status;
      if (status === 429) {
        notify("Vui lòng đợi 5 phút giữa các lần xử lý.", { type: "warning" });
        startCooldown(row.id);
      } else {
        notify(
          isSinglePage
            ? singlePageSyncErrorMessage(error)
            : (error as Error).message,
          { type: "error" },
        );
      }
    } finally {
      setProcessingId(null);
    }
  };

  const remove = async (row: ExternalSourceRow) => {
    if (
      !window.confirm(
        "Xóa nguồn đồng bộ này? Nội dung đã nhập vẫn được giữ cho Agent cho đến khi thay thế.",
      )
    ) {
      return;
    }
    try {
      if (isSinglePage) {
        await deleteSinglePageExternalSource(projectId, row.id);
      } else {
        await deleteExternalSource(projectId, row.id);
      }
      notify("Đã xóa nguồn đồng bộ.", { type: "success" });
      stopPolling();
      await load();
      suppressNextRefreshPollRef.current = isSinglePage;
      onChange?.();
    } catch (error) {
      notify(
        isSinglePage
          ? singlePageSyncErrorMessage(error)
          : (error as Error).message,
        { type: "error" },
      );
    }
  };

  if (loading) {
    return <Skeleton className="h-20 w-full" />;
  }
  if (!rows || rows.length === 0) {
    if (!isSinglePage) {
      return null;
    }
    return (
      <div
        className="rounded-lg border border-dashed border-border px-4 py-3 text-body-sm text-muted-foreground"
        aria-live="polite"
      >
        Chưa có nguồn đồng bộ Google Sheet cho trang kiến thức này.
      </div>
    );
  }

  return (
    <div className="space-y-2" aria-live="polite">
      {rows.map((row) => {
        const isProcessing = processingId === row.id;
        const isCoolingDown = cooldownId === row.id;
        const autoDisabled =
          row.last_status === "FAILED" && !row.auto_sync_enabled;
        return (
          <div
            key={row.id}
            className="project-external-source-row flex flex-col items-stretch gap-3 rounded-md border border-border p-3 sm:flex-row sm:items-center sm:gap-2"
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                {"category_key" in row && row.category_key ? (
                  <Badge variant="outline" className="font-mono">
                    {row.category_key}
                  </Badge>
                ) : null}
                {isSinglePage && (
                  <Badge variant="outline" className="font-mono">
                    gid={row.sheet_gid}
                  </Badge>
                )}
                {row.auto_sync_enabled ? (
                  <Badge variant="secondary">Tự động mỗi ngày</Badge>
                ) : (
                  <Badge variant="outline">Thủ công</Badge>
                )}
                {autoDisabled && (
                  <Badge variant="destructive">Đã tự động tắt</Badge>
                )}
                <span
                  className={cn("text-body-sm font-medium", statusTone(row))}
                >
                  {STATUS_LABEL[row.last_status] ?? row.last_status}
                </span>
              </div>
              <p
                className="mt-1 truncate text-body-sm text-muted-foreground"
                title={row.sheet_url}
              >
                {truncate(row.sheet_url)}
              </p>
              <p className="break-words text-body-sm text-muted-foreground [overflow-wrap:anywhere]">
                Đồng bộ gần nhất: {formatTimestamp(row.last_synced_at)}
                {typeof row.last_row_count === "number"
                  ? ` · ${row.last_row_count} hàng`
                  : ""}
                {row.last_status === "FAILED" && row.last_error
                  ? ` · ${
                      isSinglePage
                        ? singlePageSyncErrorMessage(row.last_error)
                        : row.last_error
                    }`
                  : ""}
              </p>
            </div>
            {mutable && (
              <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void runNow(row)}
                  disabled={disabled || isProcessing || isCoolingDown}
                  title={
                    isCoolingDown
                      ? "Vui lòng đợi 5 phút giữa các lần xử lý"
                      : undefined
                  }
                  className="min-w-0 flex-1 sm:flex-none"
                >
                  {isProcessing ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Play className="size-4" />
                  )}
                  Xử lý ngay
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => void remove(row)}
                  disabled={disabled}
                  aria-label="Xóa nguồn đồng bộ"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            )}
          </div>
        );
      })}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => void load()}
        disabled={disabled}
      >
        <RefreshCw className="size-4" />
        Làm mới
      </Button>
    </div>
  );
};
