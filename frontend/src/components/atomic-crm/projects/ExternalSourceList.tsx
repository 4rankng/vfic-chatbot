import { useCallback, useEffect, useRef, useState } from "react";
import { useNotify } from "ra-core";
import { Loader2, Play, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  deleteExternalSource,
  listExternalSources,
  runExternalSourceNow,
  type ExternalSourceSyncState,
} from "@/lib/vfic/knowledgeService";

const RUN_NOW_COOLDOWN_MS = 5 * 60 * 1000;

type Props = {
  projectId: string;
  /** Bump to force a re-fetch (parent signals after create/delete in a sibling). */
  refreshSignal?: number;
  onChange?: () => void;
  disabled?: boolean;
};

const STATUS_LABEL: Record<string, string> = {
  NEW: "Mới",
  OK: "Đã đồng bộ",
  NO_OP: "Không đổi",
  FAILED: "Lỗi",
};

const statusTone = (row: ExternalSourceSyncState): string => {
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
export const ExternalSourceList = ({ projectId, refreshSignal, onChange, disabled }: Props) => {
  const notify = useNotify();
  const [rows, setRows] = useState<ExternalSourceSyncState[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [cooldownId, setCooldownId] = useState<string | null>(null);
  const cooldownTimer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await listExternalSources(projectId));
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setLoading(false);
    }
  }, [notify, projectId]);

  useEffect(() => {
    setLoading(true);
    void load();
    return () => {
      if (cooldownTimer.current !== null) window.clearTimeout(cooldownTimer.current);
    };
  }, [load, refreshSignal]);

  const startCooldown = (id: string) => {
    setCooldownId(id);
    if (cooldownTimer.current !== null) window.clearTimeout(cooldownTimer.current);
    cooldownTimer.current = window.setTimeout(() => setCooldownId(null), RUN_NOW_COOLDOWN_MS);
  };

  const runNow = async (row: ExternalSourceSyncState) => {
    setProcessingId(row.id);
    try {
      await runExternalSourceNow(projectId, row.id);
      notify("Đang xử lý nội dung mới. Vui lòng đợi vài giây.", { type: "info" });
      startCooldown(row.id);
      // Give the worker a moment, then refresh to show the new status.
      window.setTimeout(() => void load(), 4000);
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

  const remove = async (row: ExternalSourceSyncState) => {
    if (
      !window.confirm(
        "Xóa nguồn đồng bộ này? Nội dung đã nhập vẫn được giữ cho Agent cho đến khi thay thế.",
      )
    ) {
      return;
    }
    try {
      await deleteExternalSource(projectId, row.id);
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
    return null;
  }

  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const isProcessing = processingId === row.id;
        const isCoolingDown = cooldownId === row.id;
        const autoDisabled = row.last_status === "FAILED" && !row.auto_sync_enabled;
        return (
          <div
            key={row.id}
            className="flex flex-wrap items-center gap-2 rounded-md border border-border p-3"
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="font-mono">
                  {row.category_key}
                </Badge>
                {row.auto_sync_enabled ? (
                  <Badge variant="secondary">Tự động mỗi ngày</Badge>
                ) : (
                  <Badge variant="outline">Thủ công</Badge>
                )}
                {autoDisabled && (
                  <Badge variant="destructive">Đã tự động tắt</Badge>
                )}
                <span className={cn("text-body-sm font-medium", statusTone(row))}>
                  {STATUS_LABEL[row.last_status] ?? row.last_status}
                </span>
              </div>
              <p className="mt-1 truncate text-body-sm text-muted-foreground" title={row.sheet_url}>
                {truncate(row.sheet_url)}
              </p>
              <p className="text-body-sm text-muted-foreground">
                Đồng bộ gần nhất: {formatTimestamp(row.last_synced_at)}
                {row.last_status === "FAILED" && row.last_error
                  ? ` · ${row.last_error}`
                  : ""}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void runNow(row)}
                disabled={disabled || isProcessing || isCoolingDown}
                title={isCoolingDown ? "Vui lòng đợi 5 phút giữa các lần xử lý" : undefined}
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
