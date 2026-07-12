// Typed contract + fetcher + Vietnamese presentation helpers for the
// recruiter attention dashboard (`GET /api/v1/dashboard/attention`).
//
// The backend (Phase 1) owns membership, order, dedup, and the five exact
// counters; this module performs presentation only — reason labels, elapsed
// formatting, and the reason→counter / reason→queueFilter maps used by the
// dashboard UI and the `?reason=` deep link into the inbox.
//
// Authenticated recruiters receive an anchor lead's full phone number for
// follow-up, but never the `latest_message` body.
//
// NOTE: this module intentionally does NOT consume `useDashboardStats.ts`,
// which remains live for `KnowledgeIngestPanel` and `usePerformanceStats`.

import { apiJson } from "../providers/rest/api";

/**
 * The inbox's three-valued queue chip filter. Owned here (rather than in
 * `ConversationList`) so this module — the dashboard↔inbox bridge — is the
 * single source of truth for the reason↔queue relationship, and to keep the
 * import graph acyclic (`ConversationList` imports from here, never the
 * reverse). See FIX 3 (cycle break).
 */
export type QueueFilter = "all" | "attention" | "priority";

/** Backend `AttentionReason` enum — stable machine values (descending precedence). */
export const ATTENTION_REASONS = [
  "DELIVERY_REVIEW",
  "HUMAN_ESCALATION",
  "REPLY_OVERDUE",
  "FOLLOWUP_OVERDUE",
  "WAITING_REPLY",
  "PRIORITY_NO_ACTION",
  "FOLLOWUP_TODAY",
  "UNREAD",
  "STALLED",
] as const;

export type AttentionReason = (typeof ATTENTION_REASONS)[number];

/** Backend `AttentionAction` enum — the single primary row action. */
export type AttentionAction = "OPEN_CONVERSATION" | "CALL";

/** One row of the immediate or today queue (mirrors `AttentionItemOut`). */
export interface AttentionItem {
  /** Stable dedup key: `str(conversation_id)` when present, else `"lead:{lead_id}"`. */
  key: string;
  reason: AttentionReason;
  /** ISO datetime the row is sorted by (oldest first within a reason). */
  urgency_at: string;
  conversation_id: string | null;
  lead_id: number | null;
  name: string | null;
  /** Full phone number of the anchor lead, when one has been captured. */
  phone: string | null;
  desired_job: string | null;
  lead_stage: string | null;
  lead_score: string | null;
  /** ISO datetime of the last inbound message; source of the elapsed label. */
  last_inbound_at: string | null;
  /** ISO datetime a follow-up is due, when applicable. */
  due_at: string | null;
  delivery_status: string | null;
  action: AttentionAction;
}

/** The five exact, viewer-scoped drill-down counters (mirrors `AttentionCounters`). */
export interface AttentionCounters {
  needs_reply: number;
  overdue: number;
  due_today: number;
  priority: number;
  unread: number;
}

/** Top-level attention dashboard response (mirrors `AttentionDashboardOut`). */
export interface AttentionDashboard {
  updated_at: string;
  counters: AttentionCounters;
  immediate: AttentionItem[];
  today: AttentionItem[];
}

export const ATTENTION_QUERY_KEY = ["dashboard-attention"] as const;

export const fetchAttentionDashboard = (): Promise<AttentionDashboard> =>
  apiJson<AttentionDashboard>("/api/v1/dashboard/attention");

/** Vietnamese recruiter-facing labels for each reason enum. */
export const REASON_LABELS: Record<AttentionReason, string> = {
  DELIVERY_REVIEW: "Cần xem lại tin nhắn lỗi",
  HUMAN_ESCALATION: "Cần xử lý",
  REPLY_OVERDUE: "Quá hạn phản hồi",
  FOLLOWUP_OVERDUE: "Quá hạn theo dõi",
  WAITING_REPLY: "Đang chờ phản hồi",
  PRIORITY_NO_ACTION: "Ứng viên ưu tiên cần liên hệ",
  FOLLOWUP_TODAY: "Theo dõi hôm nay",
  UNREAD: "Chưa đọc",
  STALLED: "Đang ngưng trệ",
};

/** Dashboard queues already supply context for some otherwise useful reasons. */
export type AttentionQueue = "immediate" | "today";

/**
 * Avoid repeating the purpose of the secondary queue inside its priority rows.
 * The full reason remains available to assistive technology through the row's
 * accessible name.
 */
export const reasonLabelForQueue = (
  reason: AttentionReason,
  queue: AttentionQueue,
): string | null =>
  queue === "today" && reason === "PRIORITY_NO_ACTION"
    ? null
    : REASON_LABELS[reason];

/** Vietnamese labels for the five counters (plan §Requirements). */
export const COUNTER_LABELS: Record<keyof AttentionCounters, string> = {
  needs_reply: "Cần phản hồi",
  overdue: "Quá hạn",
  due_today: "Theo dõi hôm nay",
  priority: "Ứng viên ưu tiên",
  unread: "Chưa đọc",
};

/**
 * Map a reason to the counter whose reason-group it belongs to, mirroring the
 * backend `AttentionCounters` docstring:
 *  - needs_reply = REPLY_OVERDUE + WAITING_REPLY + HUMAN_ESCALATION
 *  - overdue     = REPLY_OVERDUE + FOLLOWUP_OVERDUE
 *  - due_today   = FOLLOWUP_TODAY
 *  - priority    = PRIORITY_NO_ACTION + DELIVERY_REVIEW + STALLED
 *  - unread      = UNREAD
 *
 * `REPLY_OVERDUE` belongs to BOTH the needs_reply and overdue groups; for the
 * active-counter highlight we pick the more urgent needs_reply bucket so the
 * recruiter's eye lands on the "needs reply" action.
 */
export const counterForReason = (
  reason: AttentionReason,
): keyof AttentionCounters => {
  switch (reason) {
    case "WAITING_REPLY":
    case "HUMAN_ESCALATION":
    case "REPLY_OVERDUE":
      return "needs_reply";
    case "FOLLOWUP_OVERDUE":
      return "overdue";
    case "FOLLOWUP_TODAY":
      return "due_today";
    case "PRIORITY_NO_ACTION":
    case "DELIVERY_REVIEW":
    case "STALLED":
      return "priority";
    case "UNREAD":
      return "unread";
  }
};

/**
 * Is `value` one of the backend's stable reason enums? Used to validate a
 * `?reason=` URL param at the system boundary (the `ConversationList` mount)
 * before it flows into the data provider as a server filter.
 */
export const isAttentionReason = (
  value: string | null | undefined,
): value is AttentionReason =>
  !!value && ATTENTION_REASONS.indexOf(value as AttentionReason) !== -1;

const RELATIVE_TIME = new Intl.RelativeTimeFormat("vi", {
  numeric: "auto",
});

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/**
 * Vietnamese relative-time label for display only ("5 phút", "2 giờ", "3 ngày",
 * "khoảng 1 phút"). The endpoint remains the eligibility authority; this never
 * feeds back into 30m/24h/48h logic. Returns an empty string for unparseable
 * input so callers can omit the `<small>` cleanly.
 *
 * Clamps to "vừa xong" for sub-minute deltas to avoid "0 phút" noise.
 */
export const formatElapsed = (urgencyAt: string): string => {
  const then = Date.parse(urgencyAt);
  if (Number.isNaN(then)) return "";
  const deltaMs = Date.now() - then;
  if (deltaMs < MINUTE_MS) return "vừa xong";
  if (deltaMs < HOUR_MS) {
    const minutes = Math.round(deltaMs / MINUTE_MS);
    return `${minutes} phút`;
  }
  if (deltaMs < DAY_MS) {
    const hours = Math.round(deltaMs / HOUR_MS);
    return `${hours} giờ`;
  }
  const days = Math.round(deltaMs / DAY_MS);
  if (days < 28) return `${days} ngày`;
  // Beyond a month, a relative day count is noisy; fall back to the localized
  // auto form ("tháng trước" / "năm trước") which Intl formats correctly.
  return RELATIVE_TIME.format(-Math.round(deltaMs / DAY_MS), "day");
};

/** Maximum number of preview rows the backend returns per queue. */
export const ATTENTION_PREVIEW_LIMIT = 8;
