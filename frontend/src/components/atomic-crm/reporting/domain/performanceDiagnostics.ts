import type { PerfSlowTurn } from "./contracts";

export type Tone = "neutral" | "success" | "warning" | "danger";

export const STAGE_LABELS: Record<string, string> = {
  webhook_to_pickup: "Webhook → nhận việc",
  preamble: "Khởi tạo",
  lead: "Lấy hồ sơ ứng viên",
  system_prompt: "Xây prompt hệ thống",
  faq_bypass: "FAQ bypass",
  llm_queue: "LLM — chờ slot",
  llm_model: "LLM — xử lý model",
  llm_call_per: "LLM — mỗi lượt gọi",
  db: "Cơ sở dữ liệu",
  outbound_prepare: "Chuẩn bị adapter",
  outbound_provider: "Adapter — gọi nhà cung cấp",
  send: "Gửi Zalo",
  total: "Xử lý sau khởi tạo",
  end_to_end: "Tổng từ webhook",
};

export const LANE_LABELS: Record<string, string> = {
  agent: "Agent (LLM)",
  fast_lane: "Fast lane",
  faq_bypass: "FAQ bypass",
  unknown: "Không rõ",
};

export const OUTCOME_LABELS: Record<string, string> = {
  SENT: "Đã gửi",
  SUPPRESSED: "Đã chặn",
  ERROR: "Lỗi xử lý",
};

export const STAGE_ORDER = [
  "webhook_to_pickup",
  "preamble",
  "lead",
  "system_prompt",
  "faq_bypass",
  "llm_queue",
  "llm_model",
  "llm_call_per",
  "db",
  "outbound_prepare",
  "outbound_provider",
  "send",
  "total",
  "end_to_end",
] as const;

export const CANDIDATE_STAGES = new Set([
  "webhook_to_pickup",
  "total",
  "end_to_end",
]);

export const STAGE_TARGETS: Record<string, number> = {
  webhook_to_pickup: 200,
  preamble: 5000,
  lead: 2000,
  system_prompt: 2000,
  llm_queue: 5000,
  llm_model: 10000,
  llm_call_per: 10000,
  db: 2000,
  outbound_prepare: 500,
  outbound_provider: 1000,
  send: 1000,
  total: 10000,
  end_to_end: 10000,
};

export const formatMetricDuration = (
  value: number | null | undefined,
): string =>
  value == null
    ? "Chưa có"
    : value >= 1000
      ? `${(value / 1000).toFixed(1)} giây`
      : `${value} ms`;

export const formatCompactDuration = (
  value: number | null | undefined,
): string =>
  value == null
    ? "—"
    : value >= 1000
      ? `${(value / 1000).toFixed(1)}s`
      : `${value}ms`;

export const formatStartedAt = (value: string | null): string =>
  value ? value.replace("T", " ").slice(0, 19) : "Chưa có";

export const getStageTone = (
  key: string,
  p95: number | null | undefined,
): Tone => {
  const target = STAGE_TARGETS[key];
  if (p95 == null || target == null) return "neutral";
  if (p95 > target * 1.5) return "danger";
  if (p95 > target) return "warning";
  return "success";
};

export const getSlowTurnTone = (turn: PerfSlowTurn): Tone => {
  if (
    turn.outcome === "ERROR" ||
    turn.degraded ||
    (turn.total_ms ?? 0) > 20_000
  ) {
    return "danger";
  }
  if (turn.retried_429 || (turn.total_ms ?? 0) > 10_000) return "warning";
  return "neutral";
};

export const likelyBottleneck = (turn: PerfSlowTurn): string => {
  const stages = [
    ["LLM xử lý", turn.llm_model_ms],
    ["LLM chờ slot", turn.llm_queue_ms],
    ["Cơ sở dữ liệu", turn.db_ms],
    ["Gửi Zalo", turn.faq_bypass_ms],
  ] as const;
  const candidate = stages.reduce<(typeof stages)[number]>(
    (largest, stage) => ((stage[1] ?? 0) > (largest[1] ?? 0) ? stage : largest),
    stages[0],
  );
  return candidate[1] == null
    ? "Chưa xác định"
    : `${candidate[0]} (${formatCompactDuration(candidate[1])})`;
};
