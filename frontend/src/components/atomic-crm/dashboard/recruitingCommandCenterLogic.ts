// Pure, render-free logic for the `RecruitingCommandCenter` dashboard,
// extracted so it can be unit-tested deterministically without spinning up a
// browser (the component is a TanStack Query + react-router consumer and is
// expensive to render under Playwright). See FIX 2.
//
// The dashboard's own backend membership/count authority lives in
// `attentionDashboard.ts`; these helpers operate only on already-fetched
// `AttentionDashboard` payloads (presentation + selection state).

import {
  ATTENTION_PREVIEW_LIMIT,
  type AttentionCounters,
  type AttentionDashboard,
  type AttentionItem,
  type AttentionReason,
  counterForReason,
} from "./attentionDashboard";

export type CounterKey = keyof AttentionCounters;

/**
 * Display order of the five counter chips (matches the plan's left-to-right
 * reading: most-urgent "needs reply" first, passive "unread" last).
 */
export const COUNTER_ORDER: readonly CounterKey[] = [
  "needs_reply",
  "overdue",
  "due_today",
  "priority",
  "unread",
] as const;

/**
 * Reason that backs the `Mở hộp thư` continuation for a selected counter: the
 * single highest-precedence reason in that counter's reason-group, so the inbox
 * `?reason=` filter (which the backend takes as ONE enum) lands on the most
 * urgent slice.
 *
 * Design note (reviewer question — `overdue → REPLY_OVERDUE` excludes
 * `FOLLOWUP_OVERDUE`): the backend `?reason=` param accepts a single enum, so a
 * counter whose group spans multiple reasons (e.g. `overdue` = REPLY_OVERDUE +
 * FOLLOWUP_OVERDUE) must collapse to ONE representative for v1. We pick the more
 * urgent reason in each group. The continuation link copy deliberately does NOT
 * promise "N rows" for this reason (see `continuationLabel`) — the inbox shows
 * the representative reason's filtered set, which may be smaller than the
 * counter's cross-reason total. Multi-reason URL support is out of scope for v1.
 */
export const representativeReasonForCounter = (
  counter: CounterKey,
): AttentionReason => {
  switch (counter) {
    case "needs_reply":
      return "REPLY_OVERDUE";
    case "overdue":
      return "REPLY_OVERDUE";
    case "due_today":
      return "FOLLOWUP_TODAY";
    case "priority":
      return "PRIORITY_NO_ACTION";
    case "unread":
      return "UNREAD";
  }
};

/**
 * Presentation-only filter over the preview rows already returned by the
 * endpoint. The backend remains the membership/count authority; this never
 * recomputes 30m/24h/48h eligibility. Selecting a counter narrows BOTH queues
 * to rows whose reason rolls up to that counter.
 */
export const filterByCounter = (
  rows: AttentionItem[],
  selected: CounterKey | null,
): AttentionItem[] => {
  if (!selected) return rows;
  return rows.filter((row) => counterForReason(row.reason) === selected);
};

const HUMAN_INTERVENTION_REASONS: ReadonlySet<AttentionReason> = new Set([
  "DELIVERY_REVIEW",
  "HUMAN_ESCALATION",
  "REPLY_OVERDUE",
  "WAITING_REPLY",
]);

/**
 * Keep the "Cần can thiệp" panel limited to conversations where a person must
 * act. The backend guarantees these rows are Human-mode conversations whose
 * latest candidate message is unanswered. UNREAD alone is not a reply request.
 */
export const filterHumanInterventions = (
  rows: AttentionItem[],
): AttentionItem[] =>
  rows.filter(
    (row) =>
      HUMAN_INTERVENTION_REASONS.has(row.reason) &&
      row.action === "OPEN_CONVERSATION" &&
      row.conversation_id !== null,
  );

export type CacheDiscriminators = {
  /** Skeleton iff first load (isPending && no data yet). */
  showSkeleton: boolean;
  /** Retry pane iff the initial fetch failed and there is no cached data. */
  showInitialError: boolean;
  /** Retained data + inline error banner iff a refetch failed but data exists. */
  showPartialError: boolean;
  /** Background-refetch indicator iff we have data and a fetch is in flight. */
  showRefetchIndicator: boolean;
};

/**
 * Derive the four TanStack-Query caching-contract discriminators from raw
 * query state. Kept pure (no hooks) so the contract is unit-testable.
 *
 * Contract (Red-team Medium 14 — exact):
 *   - skeleton iff isPending && !data (first load only)
 *   - cached data + background-refetch indicator iff data && isFetching
 *     (NO skeleton flash on a routine 30s refetch)
 *   - retry pane iff isError && !data (initial failure)
 *   - retained data + error banner iff isError && data (partial failure)
 */
export const deriveCacheDiscriminators = (args: {
  isPending: boolean;
  isFetching: boolean;
  isError: boolean;
  data: AttentionDashboard | undefined;
}): CacheDiscriminators => {
  const hasData = !!args.data;
  return {
    showSkeleton: args.isPending && !hasData,
    showInitialError: args.isError && !hasData,
    showPartialError: args.isError && hasData,
    showRefetchIndicator: hasData && args.isFetching,
  };
};

/**
 * Whether to surface the `Mở hộp thư` continuation link at the bottom of a
 * panel. True iff a counter is selected, the panel has rows to follow up from,
 * and the authoritative backend counter total (`exactTotal`) exceeds the number
 * of rows currently rendered for that counter's reason group in this panel
 * (`renderedRowCount`). Falls back to a `>= ATTENTION_PREVIEW_LIMIT` heuristic
 * only when the exact counter is unavailable (no counter selected would have
 * already short-circuited via `selectedCounter === null`).
 *
 * Note the comparison is `exactTotal > renderedRowCount`, where
 * `renderedRowCount` is the panel-local filtered count (not the full preview
 * length) — because the counter total spans both queues and both relevant
 * reasons, while the panel shows one queue's slice. Surfacing the link whenever
 * the exact total beats what is visible in THIS panel is the honest "there is
 * more" signal.
 */
export const showContinuation = (args: {
  selectedCounter: CounterKey | null;
  hasRows: boolean;
  exactTotal: number | null;
  renderedRowCount: number;
  /** Total rows the endpoint returned for this panel (preview-length fallback). */
  totalCount: number;
}): boolean => {
  if (args.selectedCounter === null) return false;
  if (!args.hasRows) return false;
  if (args.exactTotal !== null) {
    return args.exactTotal > args.renderedRowCount;
  }
  return args.totalCount >= ATTENTION_PREVIEW_LIMIT;
};

/**
 * Copy for the continuation link. Per FIX 4 we deliberately do NOT promise "N
 * rows": `exactTotal` is the cross-queue counter total (e.g. `overdue` =
 * REPLY_OVERDUE + FOLLOWUP_OVERDUE across both queues), but the link navigates
 * to `?reason=<representativeReason>` which is only ONE of those reasons — so
 * the inbox filtered set may be smaller than N. The neutral "Mở hộp thư" label
 * is honest about this. (Counting it inline as context was rejected because it
 * reads as a row-count promise.)
 */
export const continuationLabel = (): string => "Mở hộp thư";
