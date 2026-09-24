import {
  rowProgressSignature,
  type ExternalSourceRowState,
} from "./externalSourceRow";

/** Follow-up cadence while a sync is still fresh. */
export const FAST_FOLLOW_UP_REFRESH_MS = 4000;
/** Follow-up cadence once the fast window has passed. */
export const SLOW_FOLLOW_UP_REFRESH_MS = 30_000;
/** Fast polls a sync gets before the cadence backs off. */
export const FAST_FOLLOW_UP_POLLS = 30;
/** Wall-clock length of the fast phase: 30 polls at 4 s. */
export const FAST_FOLLOW_UP_WINDOW_MS =
  FAST_FOLLOW_UP_POLLS * FAST_FOLLOW_UP_REFRESH_MS;

const WORKER_ATTEMPTS = 4;
const WORKER_JOB_TIMEOUT_MS = 30 * 60 * 1000;
const WORKER_RETRY_INTERVAL_MS = 2000 * 1000;

/**
 * Longest a sync can stay in flight before the backend worker gives up: four
 * 30-minute job attempts plus the 2000 s gap between retries. Follow-up polling
 * is bounded by it.
 */
export const SINGLE_PAGE_SYNC_MAX_POLL_MS =
  WORKER_ATTEMPTS * WORKER_JOB_TIMEOUT_MS +
  (WORKER_ATTEMPTS - 1) * WORKER_RETRY_INTERVAL_MS;

/**
 * A sync this list is following up on: the per-row progress signatures observed
 * when it was kicked off, and when the follow-up started.
 */
export type SyncWatch = Readonly<{
  /** When set, only this row's progress ends the watch. */
  targetId?: string;
  /** Epoch ms the watch started; anchors the fast window and the budget. */
  startedAt: number;
  /** Progress signature each candidate row had when the watch started. */
  baselineById: ReadonlyMap<string, string>;
}>;

export const createSyncWatch = (
  rows: readonly ExternalSourceRowState[],
  targetId: string | undefined,
  now: number,
): SyncWatch => ({
  targetId,
  startedAt: now,
  baselineById: new Map(rows.map((row) => [row.id, rowProgressSignature(row)])),
});

/** True once a watched row reports a terminal state its baseline never saw. */
export const syncWatchCompleted = (
  watch: SyncWatch,
  rows: readonly ExternalSourceRowState[] | undefined,
): boolean => {
  const candidates = watch.targetId
    ? (rows ?? []).filter((row) => row.id === watch.targetId)
    : (rows ?? []);
  return candidates.some((row) => {
    const settled =
      row.last_status === "OK" ||
      row.last_status === "NO_OP" ||
      row.last_status === "FAILED";
    return (
      settled && rowProgressSignature(row) !== watch.baselineById.get(row.id)
    );
  });
};

/** The backend cannot hold a single sync longer than its worker budget. */
export const syncWatchExpired = (watch: SyncWatch, now: number): boolean =>
  now - watch.startedAt >= SINGLE_PAGE_SYNC_MAX_POLL_MS;

/** True while a row is waiting on a sync the backend has not finished. */
export const rowsNeedFollowUp = (
  rows: readonly ExternalSourceRowState[] | undefined,
): boolean =>
  Boolean(
    rows?.some(
      (row) => row.last_status === "NEW" || row.last_status === "PROCESSING",
    ),
  );

/**
 * Follow-up lifecycle applied to every list result: keep the watch while the
 * sync is in flight, drop it once the sync settled or the worker budget ran
 * out, and start one when the data itself reports a sync in flight.
 */
export const resolveSyncWatch = (
  current: SyncWatch | null,
  rows: readonly ExternalSourceRowState[] | undefined,
  now: number,
): SyncWatch | null => {
  if (current) {
    return syncWatchCompleted(current, rows) || syncWatchExpired(current, now)
      ? null
      : current;
  }
  return rowsNeedFollowUp(rows)
    ? createSyncWatch(rows ?? [], undefined, now)
    : null;
};

/**
 * Delay before the next follow-up poll, derived from the rows and the age of
 * the watch: 4 s for the first 30 polls, 30 s after that, and `false` once the
 * sync settled, the worker budget ran out, or nothing is in flight.
 */
export const nextPollDelay = (
  rows: readonly ExternalSourceRowState[] | undefined,
  watch: SyncWatch | null,
  now: number,
): number | false => {
  if (!watch) {
    return rowsNeedFollowUp(rows) ? FAST_FOLLOW_UP_REFRESH_MS : false;
  }
  if (syncWatchCompleted(watch, rows) || syncWatchExpired(watch, now)) {
    return false;
  }
  return now - watch.startedAt < FAST_FOLLOW_UP_WINDOW_MS
    ? FAST_FOLLOW_UP_REFRESH_MS
    : SLOW_FOLLOW_UP_REFRESH_MS;
};
