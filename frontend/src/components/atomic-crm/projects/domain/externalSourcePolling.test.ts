import { describe, expect, it } from "vitest";
import {
  createSyncWatch,
  FAST_FOLLOW_UP_REFRESH_MS,
  FAST_FOLLOW_UP_WINDOW_MS,
  nextPollDelay,
  resolveSyncWatch,
  SINGLE_PAGE_SYNC_MAX_POLL_MS,
  SLOW_FOLLOW_UP_REFRESH_MS,
  syncWatchCompleted,
  syncWatchExpired,
} from "./externalSourcePolling";
import type { SinglePageExternalSourceSyncState } from "./project-knowledge-contracts";

const row = (
  overrides: Partial<SinglePageExternalSourceSyncState> = {},
): SinglePageExternalSourceSyncState => ({
  id: "src-1",
  project_id: "project-1",
  source_kind: "google_sheet",
  sheet_url: "https://docs.google.com/spreadsheets/d/abc/edit#gid=1",
  sheet_gid: 1,
  auto_sync_enabled: false,
  consecutive_failures: 0,
  last_status: "PROCESSING",
  created_at: "2026-07-21T10:00:00Z",
  updated_at: "2026-07-21T10:00:00Z",
  ...overrides,
});

const START = 1_000_000;

describe("external source follow-up polling", () => {
  it("polls every 4 s for 30 polls, then every 30 s until the worker budget runs out", () => {
    const watch = createSyncWatch([], undefined, START);
    const inFlight = [row()];

    expect(FAST_FOLLOW_UP_WINDOW_MS).toBe(120_000);
    expect(nextPollDelay(inFlight, watch, START)).toBe(
      FAST_FOLLOW_UP_REFRESH_MS,
    );
    expect(
      nextPollDelay(inFlight, watch, START + FAST_FOLLOW_UP_WINDOW_MS - 1),
    ).toBe(FAST_FOLLOW_UP_REFRESH_MS);
    expect(
      nextPollDelay(inFlight, watch, START + FAST_FOLLOW_UP_WINDOW_MS),
    ).toBe(SLOW_FOLLOW_UP_REFRESH_MS);
    expect(
      nextPollDelay(inFlight, watch, START + SINGLE_PAGE_SYNC_MAX_POLL_MS - 1),
    ).toBe(SLOW_FOLLOW_UP_REFRESH_MS);
    expect(
      nextPollDelay(inFlight, watch, START + SINGLE_PAGE_SYNC_MAX_POLL_MS),
    ).toBe(false);
  });

  it("does not poll while nothing is in flight", () => {
    const settled = [
      row({ last_status: "OK", last_synced_at: "2026-07-21T10:00:00Z" }),
    ];

    expect(nextPollDelay(settled, null, START)).toBe(false);
    expect(nextPollDelay([], null, START)).toBe(false);
    expect(nextPollDelay(undefined, null, START)).toBe(false);
    expect(resolveSyncWatch(null, settled, START)).toBeNull();
  });

  it("follows up on a sync the list itself reports as in flight", () => {
    const started = resolveSyncWatch(null, [row()], START);

    expect(nextPollDelay([row()], null, START)).toBe(FAST_FOLLOW_UP_REFRESH_MS);
    expect(started?.startedAt).toBe(START);
    // An unrelated poll must not restart the fast window.
    expect(resolveSyncWatch(started, [row()], START + 60_000)).toBe(started);
  });

  it("ends the watch once the watched sync settles or the budget runs out", () => {
    const baseline = row({ last_status: "NO_OP" });
    const watch = createSyncWatch([baseline], "src-1", START);
    const failed = {
      ...baseline,
      last_status: "FAILED",
      last_error: "sheet_not_public",
      updated_at: "2026-07-21T10:01:00Z",
    };

    expect(syncWatchCompleted(watch, [baseline])).toBe(false);
    expect(nextPollDelay([baseline], watch, START)).toBe(
      FAST_FOLLOW_UP_REFRESH_MS,
    );

    expect(syncWatchCompleted(watch, [failed])).toBe(true);
    expect(nextPollDelay([failed], watch, START)).toBe(false);
    expect(resolveSyncWatch(watch, [failed], START)).toBeNull();

    expect(
      syncWatchExpired(watch, START + SINGLE_PAGE_SYNC_MAX_POLL_MS - 1),
    ).toBe(false);
    expect(syncWatchExpired(watch, START + SINGLE_PAGE_SYNC_MAX_POLL_MS)).toBe(
      true,
    );
    expect(
      resolveSyncWatch(watch, [row()], START + SINGLE_PAGE_SYNC_MAX_POLL_MS),
    ).toBeNull();
  });

  it("follows only the row a run-now was started for", () => {
    const target = row({ id: "src-1", last_status: "NO_OP" });
    const sibling = row({ id: "src-2", last_status: "PROCESSING" });
    const watch = createSyncWatch([target, sibling], "src-1", START);
    const siblingFinished = {
      ...sibling,
      last_status: "OK",
      last_content_hash: "sibling-hash",
      updated_at: "2026-07-21T10:02:00Z",
    };

    expect(syncWatchCompleted(watch, [target, siblingFinished])).toBe(false);
    expect(
      syncWatchCompleted(watch, [
        {
          ...target,
          last_status: "OK",
          last_content_hash: "target-hash",
          updated_at: "2026-07-21T10:03:00Z",
        },
        siblingFinished,
      ]),
    ).toBe(true);
  });
});
