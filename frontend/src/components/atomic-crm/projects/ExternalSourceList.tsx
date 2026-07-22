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
  type ExternalSourceSyncState,
  type SinglePageExternalSourceSyncState,
} from "@/lib/vfic/knowledgeService";

const RUN_NOW_COOLDOWN_MS = 5 * 60 * 1000;
const FOLLOW_UP_REFRESH_MS = 4000;
const MAX_FOLLOW_UP_POLLS = 3;

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
  const syncSignatureRef = useRef<string | null>(null);
  const initializedSyncSignature = useRef(false);
  const isSinglePage = variant === "single-page";

  const rowsNeedFollowUp = (nextRows: ExternalSourceRow[]) =>
    nextRows.some(
      (row) =>
        row.last_status === "NEW" ||
        row.last_status === "PROCESSING" ||
        (row.last_status === "FAILED" && row.auto_sync_enabled),
    );

  const syncSignature = (nextRows: ExternalSourceRow[]) =>
    nextRows
      .filter((row) => row.last_status === "OK" || row.last_status === "NO_OP")
      .map((row) =>
        [
          row.id,
          row.last_status,
          row.last_synced_at ?? "",
          row.last_content_hash ?? "",
          row.updated_at,
        ].join(":"),
      )
      .join("|");

  const clearFollowUpTimer = () => {
    if (followUpTimer.current !== null) {
      window.clearTimeout(followUpTimer.current);
      followUpTimer.current = null;
    }
  };

  const load = useCallback(async (attempt = 0) => {
    try {
      const nextRows = isSinglePage
        ? await listSinglePageExternalSources(projectId)
        : await listExternalSources(projectId);
      setRows(nextRows);

      if (isSinglePage) {
        const nextSignature = syncSignature(nextRows);
        if (!initializedSyncSignature.current) {
          initializedSyncSignature.current = true;
        } else if (nextSignature && nextSignature !== syncSignatureRef.current) {
          onSynchronized?.();
        }
        syncSignatureRef.current = nextSignature;

        clearFollowUpTimer();
        if (attempt < MAX_FOLLOW_UP_POLLS && rowsNeedFollowUp(nextRows)) {
          followUpTimer.current = window.setTimeout(
            () => void load(attempt + 1),
            FOLLOW_UP_REFRESH_MS,
          );
        }
      }
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setLoading(false);
    }
  }, [isSinglePage, notify, onSynchronized, projectId]);

  useEffect(() => {
    return () => {
      if (cooldownTimer.current !== null)
        window.clearTimeout(cooldownTimer.current);
      clearFollowUpTimer();
    };
  }, []);

  useEffect(() => {
    setLoading(true);
    void load();
    return () => {
      clearFollowUpTimer();
    };
  }, [load, refreshSignal]);

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
      clearFollowUpTimer();
      followUpTimer.current = window.setTimeout(
        () => void load(),
        FOLLOW_UP_REFRESH_MS,
      );
    } catch (error) {
      const status = (error as { status?: number }).status;
      if (status === 429) {
        notify("Vui lòng đợi 5 phút giữa các lần xử lý.", { type: "warning" });
        startCooldown(row.id);
      } else {
        notify((error as Error).message, { type: "error" });
      }
    } finally {
      setProcessingId(null);
      onChange?.();
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
      await load();
      onChange?.();
    } catch (error) {
      notify((error as Error).message, { type: "error" });
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
                  ? ` · ${row.last_error}`
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
