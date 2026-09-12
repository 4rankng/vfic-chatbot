// Logic-level tests for the RecruitingCommandCenter dashboard.
//
// The component is a TanStack Query + react-router consumer that is expensive
// to render under Playwright; the testable behaviour (counter selection state
// machine, cache-contract discriminators, continuation boundary, representative
// reason mapping) is extracted into `recruitingCommandCenterLogic.ts` and
// exercised here deterministically. See FIX 2.
//
// What is NOT covered here (and why): full React render tests for loading /
// success / retry / cached-refetch UX. The pure derivation of those UI states
// IS covered (`deriveCacheDiscriminators`); wiring it to TanStack Query is a
// thin one-liner verified by typecheck + the existing `attentionDashboard.test`
// fetcher test. A browser render test is tracked as a follow-up.

import { describe, expect, it } from "vitest";

import {
  ATTENTION_REASONS,
  type AttentionDashboard,
  type AttentionItem,
  type AttentionReason,
  counterForReason,
} from "./attentionDashboard";
import {
  COUNTER_ORDER,
  continuationLabel,
  deriveCacheDiscriminators,
  filterByCounter,
  filterHumanInterventions,
  representativeReasonForCounter,
  showContinuation,
} from "./recruitingCommandCenterLogic";

/** Build a minimal row; only `key` + `reason` drive the logic under test. */
const row = (
  key: string,
  reason: AttentionReason,
  partial: Partial<AttentionItem> = {},
): AttentionItem => ({
  key,
  reason,
  urgency_at: "2026-07-12T09:00:00Z",
  conversation_id: `conv-${key}`,
  lead_id: null,
  name: `Ứng viên ${key}`,
  phone: null,
  desired_job: null,
  lead_stage: null,
  lead_score: null,
  last_inbound_at: null,
  due_at: null,
  delivery_status: null,
  action: "OPEN_CONVERSATION",
  ...partial,
});

const dashboard = (
  overrides: Partial<AttentionDashboard> = {},
): AttentionDashboard => ({
  updated_at: "2026-07-12T10:00:00Z",
  counters: {
    needs_reply: 0,
    overdue: 0,
    due_today: 0,
    priority: 0,
    unread: 0,
  },
  immediate: [],
  today: [],
  ...overrides,
});

describe("COUNTER_ORDER", () => {
  it("lists exactly the five counters in the urgent-first display order", () => {
    expect(COUNTER_ORDER).toEqual([
      "needs_reply",
      "overdue",
      "due_today",
      "priority",
      "unread",
    ]);
  });

  it("has no duplicate entries", () => {
    expect(new Set(COUNTER_ORDER).size).toBe(COUNTER_ORDER.length);
  });
});

describe("representativeReasonForCounter", () => {
  // Documents the v1 single-reason drill-down (reviewer question).
  it("maps each counter to ONE valid backend reason enum", () => {
    for (const counter of COUNTER_ORDER) {
      const reason = representativeReasonForCounter(counter);
      expect(ATTENTION_REASONS, `representative for ${counter}`).toContain(
        reason,
      );
    }
  });

  it("picks the most urgent reason inside each counter's group", () => {
    // `overdue` = REPLY_OVERDUE + FOLLOWUP_OVERDUE; REPLY_OVERDUE is the more
    // urgent of the two and is the documented v1 representative. The
    // continuation copy deliberately makes no "N rows" promise to stay honest
    // about excluding FOLLOWUP_OVERDUE.
    expect(representativeReasonForCounter("overdue")).toBe("REPLY_OVERDUE");
    expect(representativeReasonForCounter("needs_reply")).toBe("REPLY_OVERDUE");
    expect(representativeReasonForCounter("due_today")).toBe("FOLLOWUP_TODAY");
    expect(representativeReasonForCounter("priority")).toBe(
      "PRIORITY_NO_ACTION",
    );
    expect(representativeReasonForCounter("unread")).toBe("UNREAD");
  });

  it("the representative rolls up to the same counter it represents, EXCEPT overdue (documented asymmetry)", () => {
    // For four of the five counters the representative reason routes back to
    // that counter under `counterForReason`. The single exception is
    // `overdue`: its representative `REPLY_OVERDUE` belongs to BOTH the
    // needs_reply and overdue groups, and `counterForReason` deliberately
    // routes it to the more urgent `needs_reply` bucket (for the active-counter
    // highlight). This is the reviewer-flagged REPLY_OVERDUE overlap. The
    // `overdue` drill-down still works — `filterByCounter` is reason-set based
    // — but the inbox `?reason=REPLY_OVERDUE` filter lands on a reason whose
    // active-counter highlight would be `needs_reply`, not `overdue`. v1
    // accepts this; multi-reason URL support would remove it.
    for (const counter of COUNTER_ORDER) {
      const reason = representativeReasonForCounter(counter);
      const rollsUpTo = counterForReason(reason);
      if (counter === "overdue") {
        expect(rollsUpTo, `overdue rep ${reason} rolls to needs_reply`).toBe(
          "needs_reply",
        );
      } else {
        expect(rollsUpTo, `${counter} rep ${reason}`).toBe(counter);
      }
    }
  });
});

describe("filterByCounter", () => {
  const rows: AttentionItem[] = [
    row("a", "REPLY_OVERDUE"), // needs_reply + overdue
    row("b", "FOLLOWUP_OVERDUE"), // overdue
    row("c", "FOLLOWUP_TODAY"), // due_today
    row("d", "UNREAD"), // unread
    row("e", "PRIORITY_NO_ACTION"), // priority
  ];

  it("returns the rows unchanged when no counter is selected", () => {
    expect(filterByCounter(rows, null)).toBe(rows);
    expect(filterByCounter([], null)).toEqual([]);
  });

  it("narrows to rows whose reason rolls up to the selected counter", () => {
    // NOTE the `overdue` counter only catches FOLLOWUP_OVERDUE here, NOT row
    // `a` (REPLY_OVERDUE): `counterForReason` routes REPLY_OVERDUE to the more
    // urgent `needs_reply` bucket (the documented active-highlight asymmetry).
    // The `overdue` drill-down therefore surfaces the FOLLOWUP_OVERDUE slice;
    // its continuation link still targets the representative REPLY_OVERDUE
    // reason — see `representativeReasonForCounter`.
    expect(filterByCounter(rows, "overdue").map((r) => r.key)).toEqual(["b"]);
    expect(filterByCounter(rows, "due_today").map((r) => r.key)).toEqual(["c"]);
    expect(filterByCounter(rows, "unread").map((r) => r.key)).toEqual(["d"]);
    expect(filterByCounter(rows, "priority").map((r) => r.key)).toEqual(["e"]);
    expect(filterByCounter(rows, "needs_reply").map((r) => r.key)).toEqual([
      "a",
    ]);
  });

  it("never recomputes reason eligibility — it only groups by counterForReason", () => {
    // filterByCounter follows counterForReason exactly; it does not run a
    // separate 30m/24h/48h calc. Adding a second needs-reply reason confirms
    // the grouping, not the urgency, drives membership.
    const withWaiting = [
      ...rows,
      row("f", "WAITING_REPLY"),
      row("g", "HUMAN_ESCALATION"),
    ];
    expect(
      filterByCounter(withWaiting, "needs_reply").map((r) => r.key),
    ).toEqual(["a", "f", "g"]);
  });
});

describe("filterHumanInterventions", () => {
  it("includes every unanswered-human reason, including a new inbound inside 30 minutes", () => {
    const rows = [
      row("unread", "UNREAD"),
      row("waiting", "WAITING_REPLY"),
      row("escalated", "HUMAN_ESCALATION"),
      row("failed", "DELIVERY_REVIEW"),
      row("overdue", "REPLY_OVERDUE"),
    ];

    expect(filterHumanInterventions(rows).map((item) => item.key)).toEqual([
      "waiting",
      "escalated",
      "failed",
      "overdue",
    ]);
  });

  it("requires an openable conversation", () => {
    expect(
      filterHumanInterventions([
        row("lead-only", "HUMAN_ESCALATION", {
          conversation_id: null,
          action: "CALL",
        }),
      ]),
    ).toEqual([]);
  });
});

describe("deriveCacheDiscriminators", () => {
  const payload = dashboard();

  it("shows a skeleton only on the first load (isPending && no data)", () => {
    const d = deriveCacheDiscriminators({
      isPending: true,
      isFetching: true,
      isError: false,
      data: undefined,
    });
    expect(d.showSkeleton).toBe(true);
    expect(d.showInitialError).toBe(false);
    expect(d.showPartialError).toBe(false);
    expect(d.showRefetchIndicator).toBe(false);
  });

  it("shows the success state with no skeleton/error once data is loaded and idle", () => {
    const d = deriveCacheDiscriminators({
      isPending: false,
      isFetching: false,
      isError: false,
      data: payload,
    });
    expect(d.showSkeleton).toBe(false);
    expect(d.showInitialError).toBe(false);
    expect(d.showPartialError).toBe(false);
    expect(d.showRefetchIndicator).toBe(false);
  });

  it("shows the refetch indicator (NOT a skeleton) on a background refetch with cached data", () => {
    // Red-team Medium 14: the 30s background refetch must NOT flash a skeleton.
    const d = deriveCacheDiscriminators({
      isPending: false,
      isFetching: true,
      isError: false,
      data: payload,
    });
    expect(d.showSkeleton).toBe(false);
    expect(d.showRefetchIndicator).toBe(true);
    expect(d.showPartialError).toBe(false);
  });

  it("shows the retry pane (not partial error) when the INITIAL fetch fails with no cached data", () => {
    const d = deriveCacheDiscriminators({
      isPending: false,
      isFetching: false,
      isError: true,
      data: undefined,
    });
    expect(d.showInitialError).toBe(true);
    expect(d.showPartialError).toBe(false);
    expect(d.showSkeleton).toBe(false);
  });

  it("shows retained data + the partial-error banner when a REFETCH fails but cached data exists", () => {
    const d = deriveCacheDiscriminators({
      isPending: false,
      isFetching: false,
      isError: true,
      data: payload,
    });
    expect(d.showPartialError).toBe(true);
    expect(d.showInitialError).toBe(false);
    expect(d.showSkeleton).toBe(false);
    expect(d.showRefetchIndicator).toBe(false);
  });

  it("partial error wins over refetch indicator when both error and fetching are true with data", () => {
    // A refetch that errors still leaves the previous data visible; both the
    // partial-error banner and the spinner could apply, but the banner is the
    // actionable signal — keep both surfaced (the component renders them in
    // different regions) and assert they are independently correct.
    const d = deriveCacheDiscriminators({
      isPending: false,
      isFetching: true,
      isError: true,
      data: payload,
    });
    expect(d.showPartialError).toBe(true);
    expect(d.showRefetchIndicator).toBe(true);
    expect(d.showSkeleton).toBe(false);
  });
});

describe("showContinuation", () => {
  it("is false when no counter is selected (the preview is the whole queue)", () => {
    expect(
      showContinuation({
        selectedCounter: null,
        hasRows: true,
        exactTotal: 99,
        renderedRowCount: 1,
        totalCount: 8,
      }),
    ).toBe(false);
  });

  it("is false when the panel has no rows to follow up from", () => {
    expect(
      showContinuation({
        selectedCounter: "overdue",
        hasRows: false,
        exactTotal: 5,
        renderedRowCount: 0,
        totalCount: 0,
      }),
    ).toBe(false);
  });

  it("is true when the exact counter total exceeds the rendered rows for this panel", () => {
    // exactTotal (cross-queue counter) > renderedRowCount (this panel's slice).
    expect(
      showContinuation({
        selectedCounter: "overdue",
        hasRows: true,
        exactTotal: 12,
        renderedRowCount: 4,
        totalCount: 8,
      }),
    ).toBe(true);
  });

  it("is false when the exact total fits inside the rendered rows", () => {
    expect(
      showContinuation({
        selectedCounter: "overdue",
        hasRows: true,
        exactTotal: 3,
        renderedRowCount: 3,
        totalCount: 8,
      }),
    ).toBe(false);
  });

  it("falls back to the preview-length heuristic when exactTotal is null", () => {
    // No counter selected would have short-circuited; here a counter IS
    // selected but the exact total is unavailable, so we use totalCount >= 8.
    expect(
      showContinuation({
        selectedCounter: "overdue",
        hasRows: true,
        exactTotal: null,
        renderedRowCount: 5,
        totalCount: 8,
      }),
    ).toBe(true);
    expect(
      showContinuation({
        selectedCounter: "overdue",
        hasRows: true,
        exactTotal: null,
        renderedRowCount: 5,
        totalCount: 7,
      }),
    ).toBe(false);
  });

  it("uses the panel-local rendered count, not the full preview length, for the boundary", () => {
    // The counter total spans both queues; the panel shows one queue's slice.
    // exactTotal = 10, renderedRowCount = 6 in this panel -> there are more
    // rows elsewhere, so the link shows.
    expect(
      showContinuation({
        selectedCounter: "overdue",
        hasRows: true,
        exactTotal: 10,
        renderedRowCount: 6,
        totalCount: 8,
      }),
    ).toBe(true);
  });
});

describe("continuationLabel", () => {
  it("returns the neutral Vietnamese 'Mở hộp thư' with no row-count promise (FIX 4)", () => {
    expect(continuationLabel()).toBe("Mở hộp thư");
    // The label must NOT embed a number — the counter total spans multiple
    // reasons while `?reason=` drills into one, so promising N would be
    // dishonest.
    expect(continuationLabel()).not.toMatch(/\d/);
  });
});
