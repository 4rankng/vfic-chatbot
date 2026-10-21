import type { AttentionCounters } from "./attentionDashboard";

/**
 * Dashboard KPI cards (phone-first section). Pure composition over the
 * metrics snapshot plus the already-fetched lead rows: the `/dashboard/metrics`
 * endpoint is current-state, so every "so sánh kỳ trước" comparison is derived
 * from the fetched leads' `created_at` (the dashboard already loads the 200
 * most recent). When those rows do not reach back a full comparison window the
 * delta degrades to "—" instead of reporting a truncated trend.
 */

/** One fetched lead row reduced to the fields the KPI math needs. */
export type KpiLeadRow = {
  created_at: string;
  lead_stage?: string | null;
};

/** Structural subset of `/api/v1/dashboard/metrics` (DashboardMetrics). */
export type DashboardMetricsSnapshot = {
  total_leads?: number | null;
  hired_rate?: number | null;
  open_conversations?: number | null;
  unread_conversation_count?: number | null;
  stage_breakdown?: readonly {
    value: string;
    count: number;
    percentage: number;
  }[];
};

export type KpiTone = "good" | "bad" | "neutral";

export type KpiDelta = {
  direction: "up" | "down" | "flat";
  /** Preformatted change, or null when the previous window is not covered. */
  text: string | null;
  tone: KpiTone;
  label: string;
};

export type KpiCard = {
  id: "pipeline" | "new-leads" | "conversion" | "open-conversations";
  label: string;
  value: string;
  caption?: string;
  delta?: KpiDelta;
  emphasis: "headline" | "normal";
};

export const KPI_WINDOW_DAYS = 7;

const DAY_MS = 86_400_000;
const numberFormat = new Intl.NumberFormat("vi-VN");

/** Canonical stage labels for the pipeline caption (types.ts LEAD_STAGES order). */
const STAGE_LABELS: Record<string, string> = {
  NEW: "Mới",
  CONTACTING: "Đang liên hệ",
  REGISTERED: "Đã đăng ký",
  SKIPPED: "Bỏ qua",
};

type WindowCounts = {
  current: number;
  previous: number;
  currentRegistered: number;
  previousRegistered: number;
  /** True when the fetched rows reach back through both full windows. */
  covered: boolean;
};

const countWindows = (
  leads: readonly KpiLeadRow[],
  nowMs: number,
): WindowCounts => {
  const currentStart = nowMs - KPI_WINDOW_DAYS * DAY_MS;
  const previousStart = nowMs - 2 * KPI_WINDOW_DAYS * DAY_MS;
  let current = 0;
  let previous = 0;
  let currentRegistered = 0;
  let previousRegistered = 0;
  let earliest = Number.POSITIVE_INFINITY;
  for (const row of leads) {
    const createdMs = Date.parse(row.created_at);
    if (!Number.isFinite(createdMs)) continue;
    if (createdMs < earliest) earliest = createdMs;
    const registered = row.lead_stage === "REGISTERED";
    if (createdMs >= currentStart) {
      current += 1;
      if (registered) currentRegistered += 1;
    } else if (createdMs >= previousStart) {
      previous += 1;
      if (registered) previousRegistered += 1;
    }
  }
  return {
    current,
    previous,
    currentRegistered,
    previousRegistered,
    covered: leads.length > 0 && earliest <= previousStart,
  };
};

const signed = (value: number): string =>
  value > 0 ? `+${value}` : String(value);

const growthDelta = (
  current: number,
  previous: number,
  counts: WindowCounts,
  label: string,
): KpiDelta => {
  const direction =
    current > previous ? "up" : current < previous ? "down" : "flat";
  const tone: KpiTone =
    direction === "up" ? "good" : direction === "down" ? "bad" : "neutral";
  if (!counts.covered) return { direction, text: null, tone, label };
  if (previous === 0) {
    return {
      direction,
      text: current > 0 ? "kỳ trước: 0" : "0%",
      tone,
      label,
    };
  }
  const pct = Math.round(((current - previous) / previous) * 100);
  return { direction, text: `${signed(pct)}%`, tone, label };
};

const conversionDelta = (counts: WindowCounts, label: string): KpiDelta => {
  const currentRate =
    counts.current > 0 ? (counts.currentRegistered / counts.current) * 100 : 0;
  const previousRate =
    counts.previous > 0
      ? (counts.previousRegistered / counts.previous) * 100
      : 0;
  const change = currentRate - previousRate;
  const direction = change > 0.05 ? "up" : change < -0.05 ? "down" : "flat";
  const tone: KpiTone =
    direction === "up" ? "good" : direction === "down" ? "bad" : "neutral";
  if (!counts.covered || (counts.current === 0 && counts.previous === 0)) {
    return { direction, text: null, tone, label };
  }
  return {
    direction,
    text: `${signed(Math.round(change * 10) / 10)} điểm`,
    tone,
    label,
  };
};

export const buildKpiCards = (input: {
  metrics?: DashboardMetricsSnapshot | null;
  counters?: AttentionCounters | null;
  leads: readonly KpiLeadRow[];
  now?: Date;
}): KpiCard[] => {
  const metrics = input.metrics ?? null;
  const counters = input.counters ?? null;
  const nowMs = (input.now ?? new Date()).getTime();
  const counts = countWindows(input.leads, nowMs);

  const todayStart = new Date(nowMs);
  todayStart.setHours(0, 0, 0, 0);
  const yesterdayStart = todayStart.getTime() - DAY_MS;
  let today = 0;
  let yesterday = 0;
  for (const row of input.leads) {
    const createdMs = Date.parse(row.created_at);
    if (!Number.isFinite(createdMs) || createdMs < yesterdayStart) continue;
    if (createdMs >= todayStart.getTime()) today += 1;
    else yesterday += 1;
  }

  const stageCaption = (metrics?.stage_breakdown ?? [])
    .filter((stage) => stage.count > 0)
    .map(
      (stage) => `${STAGE_LABELS[stage.value] ?? stage.value} ${stage.count}`,
    )
    .join(" · ");

  const totalLeads = metrics?.total_leads ?? 0;
  const pipelineDelta: KpiDelta = {
    direction: today > yesterday ? "up" : today < yesterday ? "down" : "flat",
    text: `${signed(today)} hôm nay`,
    tone: today > yesterday ? "good" : today < yesterday ? "bad" : "neutral",
    label: `so với hôm qua (+${yesterday})`,
  };

  const conversionRate = metrics?.hired_rate ?? 0;
  const openConversations = metrics?.open_conversations ?? 0;
  const needsReply = counters?.needs_reply ?? 0;
  const humanHandoffs = metrics?.unread_conversation_count ?? 0;
  const openCaptionParts = [
    needsReply > 0 ? `${needsReply} cần phản hồi` : null,
    humanHandoffs > 0 ? `${humanHandoffs} cần người xử lý` : null,
  ].filter((part): part is string => part !== null);

  return [
    {
      id: "pipeline",
      label: "Pipeline ứng viên",
      value: numberFormat.format(totalLeads),
      caption: stageCaption || "Chưa có dữ liệu phễu",
      delta: pipelineDelta,
      emphasis: "headline",
    },
    {
      id: "new-leads",
      label: `Ứng viên mới (${KPI_WINDOW_DAYS} ngày)`,
      value: numberFormat.format(counts.current),
      delta: growthDelta(
        counts.current,
        counts.previous,
        counts,
        `so với ${KPI_WINDOW_DAYS} ngày trước`,
      ),
      emphasis: "normal",
    },
    {
      id: "conversion",
      label: "Tỷ lệ chuyển đổi",
      value: `${Math.round(conversionRate)}%`,
      caption: "Đã đăng ký / tổng ứng viên",
      delta: conversionDelta(
        counts,
        `so với kỳ trước (${KPI_WINDOW_DAYS} ngày)`,
      ),
      emphasis: "normal",
    },
    {
      id: "open-conversations",
      label: "Hội thoại đang mở",
      value: numberFormat.format(openConversations),
      caption: openCaptionParts.join(" · ") || "Không có hội thoại chờ xử lý",
      emphasis: "normal",
    },
  ];
};
