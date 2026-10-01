import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNotify } from "ra-core";
import { Link2 } from "lucide-react";
import { EmptyState } from "../kit";
import { Button } from "@/components/ui/button";
import {
  createSyncWatch,
  nextPollDelay,
  resolveSyncWatch,
  syncWatchExpired,
  type SyncWatch,
} from "./domain/externalSourcePolling";
import {
  successfulSyncSignature,
  type ExternalSourceRowState,
} from "./domain/externalSourceRow";
import { ExternalSourceRow } from "./presentation/ExternalSourceRow";
import {
  deleteExternalSource,
  deleteSinglePageExternalSource,
  listExternalSources,
  listSinglePageExternalSources,
  runExternalSourceNow,
  runSinglePageExternalSourceNow,
  singlePageSyncErrorMessage,
} from "./project-knowledge-service";

const RUN_NOW_COOLDOWN_MS = 5 * 60 * 1000;

type Variant = "category" | "single-page";

type Props = {
  projectId: string;
  /** Bump to force a re-fetch (parent signals after create/delete in a sibling). */
  refreshSignal?: number;
  onChange?: () => void;
  disabled?: boolean;
  variant?: Variant;
  mutable?: boolean;
  onSynchronized?: () => void;
};

const externalSourcesQueryKey = (projectId: string, variant: Variant) =>
  ["external-sources", projectId, variant] as const;

/**
 * Read-only list of configured external sources for a project. Auto-sync state
 * is shown but not editable inline (delete + re-create to change it). Each row
 * has a "Process now" button (5-minute cooldown) and a "Remove" button.
 *
 * Follow-up polling is delegated to TanStack Query: `refetchInterval` is
 * derived from the rows themselves (4 s while a sync is fresh, then 30 s, then
 * no polling once it settles) and TanStack skips the interval while the tab is
 * hidden.
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
  const queryClient = useQueryClient();
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [cooldownId, setCooldownId] = useState<string | null>(null);
  const [watch, setWatch] = useState<SyncWatch | null>(null);
  const cooldownTimer = useRef<number | null>(null);
  /** Set by a delete so the parent's refresh signal does not start a poll. */
  const suppressNextRefreshPollRef = useRef(false);
  const previousRefreshSignalRef = useRef({ projectId, value: refreshSignal });
  const syncSignatureRef = useRef<string | null>(null);
  const contextRef = useRef(0);
  const mutationPendingRef = useRef(false);
  const isSinglePage = variant === "single-page";
  const queryKey = useMemo(
    () => externalSourcesQueryKey(projectId, variant),
    [projectId, variant],
  );

  const query = useQuery<ExternalSourceRowState[]>({
    queryKey,
    queryFn: ({ signal }) =>
      isSinglePage
        ? listSinglePageExternalSources(projectId, signal)
        : listExternalSources(projectId, signal),
    // Follow-up cadence comes from the row data, never from a poll counter.
    refetchInterval: (current) =>
      nextPollDelay(current.state.data, watch, Date.now()),
    // A hidden tab must not keep hitting the backend: TanStack skips the
    // interval refetch while the document is not visible.
    refetchIntervalInBackground: false,
    // The interval is the only refresh source this list ever had; a focus
    // refetch on top of it would add requests the old poller never made.
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { error, errorUpdatedAt, isError } = query;
  const rows = query.data;

  // A different project (or variant) is a different list: no watch, no baseline
  // from the previous one, and no leftover cooldown.
  useEffect(() => {
    setWatch(null);
    setCooldownId(null);
    setProcessingId(null);
    setRemovingId(null);
    mutationPendingRef.current = false;
    syncSignatureRef.current = null;
    suppressNextRefreshPollRef.current = false;
    return () => {
      contextRef.current += 1;
      if (cooldownTimer.current !== null) {
        window.clearTimeout(cooldownTimer.current);
        cooldownTimer.current = null;
      }
    };
  }, [isSinglePage, projectId]);

  // Follow-up lifecycle: drop the watch once the watched sync settled or the
  // worker budget ran out, and pick one up when the data reports a sync.
  useEffect(() => {
    if (!rows) return;
    setWatch((current) => resolveSyncWatch(current, rows, Date.now()));
  }, [rows]);

  // A changed successful-sync signature means sheet content actually moved; the
  // parent uses that to reload the page knowledge it renders.
  useEffect(() => {
    if (!isSinglePage || !rows) return;
    const signature = successfulSyncSignature(rows);
    const previous = syncSignatureRef.current;
    syncSignatureRef.current = signature;
    if (previous !== null && signature !== "" && signature !== previous) {
      onSynchronized?.();
    }
  }, [isSinglePage, onSynchronized, rows]);

  useEffect(() => {
    if (!isError || !error) return;
    notify(
      isSinglePage
        ? singlePageSyncErrorMessage(error)
        : (error as Error).message,
      { type: "error" },
    );
  }, [error, errorUpdatedAt, isError, isSinglePage, notify]);

  const refresh = useCallback(async () => {
    // Replace any in-flight request so the newest response is the one that
    // reaches the list.
    await queryClient.cancelQueries({ queryKey });
    await query.refetch();
  }, [query, queryClient, queryKey]);

  // The parent bumps refreshSignal after it changes a source elsewhere: fetch
  // again, and for single-page follow the sync up even if the row is not there
  // yet.
  useEffect(() => {
    const previous = previousRefreshSignalRef.current;
    previousRefreshSignalRef.current = { projectId, value: refreshSignal };
    if (previous.projectId !== projectId || previous.value === refreshSignal) {
      return;
    }
    const suppressPoll = suppressNextRefreshPollRef.current;
    suppressNextRefreshPollRef.current = false;
    const currentRows =
      queryClient.getQueryData<ExternalSourceRowState[]>(queryKey) ?? [];
    if (isSinglePage && !suppressPoll && currentRows.length === 0) {
      // The parent just changed a source. The row can still be missing from the
      // list, so follow the sync up even though the list is empty.
      const now = Date.now();
      setWatch((current) =>
        current && !syncWatchExpired(current, now)
          ? current
          : createSyncWatch([], undefined, now),
      );
    }
    void refresh();
  }, [isSinglePage, projectId, queryClient, queryKey, refresh, refreshSignal]);

  const startCooldown = (id: string) => {
    setCooldownId(id);
    if (cooldownTimer.current !== null) {
      window.clearTimeout(cooldownTimer.current);
    }
    cooldownTimer.current = window.setTimeout(
      () => setCooldownId(null),
      RUN_NOW_COOLDOWN_MS,
    );
  };

  const runNow = async (row: ExternalSourceRowState) => {
    if (disabled || !mutable || mutationPendingRef.current) return;
    const context = contextRef.current;
    mutationPendingRef.current = true;
    setProcessingId(row.id);
    try {
      if (isSinglePage) {
        await runSinglePageExternalSourceNow(projectId, row.id);
      } else {
        await runExternalSourceNow(projectId, row.id);
      }
      if (context !== contextRef.current) return;
      notify("Đang xử lý nội dung mới. Vui lòng đợi vài giây.", {
        type: "info",
      });
      startCooldown(row.id);
      if (isSinglePage) {
        // A fresh sync started for this row: follow it up from what it shows now.
        setWatch(createSyncWatch(rows ?? [], row.id, Date.now()));
      }
    } catch (error) {
      if (context !== contextRef.current) return;
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
      if (context === contextRef.current) {
        mutationPendingRef.current = false;
        setProcessingId(null);
      }
    }
  };

  const remove = async (row: ExternalSourceRowState) => {
    if (disabled || !mutable || mutationPendingRef.current) return;
    if (
      !window.confirm(
        "Xóa nguồn đồng bộ này? Nội dung đã nhập vẫn được giữ cho chatbot cho đến khi thay thế.",
      )
    ) {
      return;
    }
    const context = contextRef.current;
    mutationPendingRef.current = true;
    setRemovingId(row.id);
    try {
      if (isSinglePage) {
        await deleteSinglePageExternalSource(projectId, row.id);
      } else {
        await deleteExternalSource(projectId, row.id);
      }
      if (context !== contextRef.current) return;
      notify("Đã xóa nguồn đồng bộ.", { type: "success" });
      setWatch(null);
      await refresh();
      if (context !== contextRef.current) return;
      suppressNextRefreshPollRef.current = isSinglePage;
      onChange?.();
    } catch (error) {
      if (context !== contextRef.current) return;
      notify(
        isSinglePage
          ? singlePageSyncErrorMessage(error)
          : (error as Error).message,
        { type: "error" },
      );
    } finally {
      if (context === contextRef.current) {
        mutationPendingRef.current = false;
        setRemovingId(null);
      }
    }
  };

  if (query.isLoading) {
    return (
      <div className="uu-scope" role="status" aria-label="Đang tải danh sách">
        <span className="block h-20 w-full animate-pulse rounded-lg bg-tertiary" />
      </div>
    );
  }
  const loadError = isError ? (
    <div
      role="alert"
      className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-body-sm"
    >
      <p className="font-medium">Chưa tải được nguồn đồng bộ.</p>
      <p className="mt-1 text-muted-foreground">
        Thử lại để xem trạng thái mới nhất.
      </p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-2"
        disabled={query.isFetching}
        onClick={() => void refresh()}
      >
        {query.isFetching ? "Đang tải…" : "Thử lại"}
      </Button>
    </div>
  ) : null;
  if (!rows || rows.length === 0) {
    if (loadError) return loadError;
    if (!isSinglePage) {
      return null;
    }
    return (
      <EmptyState
        icon={<Link2 className="size-6" aria-hidden="true" />}
        title="Nguồn đồng bộ"
        description="Chưa có nguồn đồng bộ Google Sheet cho trang kiến thức này."
      />
    );
  }

  return (
    <div
      className="space-y-2"
      aria-live="polite"
      aria-busy={query.isFetching || !!processingId || !!removingId}
    >
      {loadError}
      {rows.map((row) => (
        <ExternalSourceRow
          key={row.id}
          row={row}
          isSinglePage={isSinglePage}
          mutable={mutable}
          disabled={disabled || !!processingId || !!removingId}
          processing={processingId === row.id}
          removing={removingId === row.id}
          coolingDown={cooldownId === row.id}
          onRunNow={(target) => void runNow(target)}
          onRemove={(target) => void remove(target)}
        />
      ))}
    </div>
  );
};
