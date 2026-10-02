import {
  STAGE_TARGETS,
  formatMetricDuration as fmtMs,
  getStageTone,
  type Tone,
} from "../../reporting/domain/performanceDiagnostics";
import type { PerfMetrics } from "../usePerformanceStats";

export type SignalKind =
  | "latency"
  | "rate-limit"
  | "failed"
  | "unknown"
  | "capacity"
  | "stable";

export interface Signal {
  id: SignalKind;
  tone: Tone;
  title: string;
  detail: string;
  value: string;
}

/**
 * Rank every live abnormality — p95 latency, LLM rate limiting, delivery
 * outcomes, worker saturation — into one ordered queue. The health band and
 * the attention window both read this, so the verdict the operator sees first
 * can never disagree with the signals listed below it.
 */
export const collectSignals = (data: PerfMetrics): Signal[] => {
  const endToEnd = data.percentiles.end_to_end?.p95;
  const delivery = data.reliability;
  const signals: Signal[] = [];
  if (endToEnd != null && endToEnd > STAGE_TARGETS.end_to_end)
    signals.push({
      id: "latency",
      tone: getStageTone("end_to_end", endToEnd),
      title: "Độ trễ p95 vượt mục tiêu",
      detail: "Ứng viên có thể phải chờ phản hồi lâu hơn kỳ vọng.",
      value: fmtMs(endToEnd),
    });
  if (data.live.minimax_429s_last_1m > 0)
    signals.push({
      id: "rate-limit",
      tone: "warning",
      title: "LLM có phản hồi 429",
      detail: "Đã có retry hoặc nguy cơ làm chậm các lượt mới.",
      value: `${data.live.minimax_429s_last_1m} trong 1 phút`,
    });
  if ((delivery?.failed_count ?? 0) > 0)
    signals.push({
      id: "failed",
      tone: "danger",
      title: "Có lượt gửi thất bại",
      detail: "Kiểm tra các lượt chậm để xác nhận việc giao tin nhắn.",
      value: String(delivery?.failed_count),
    });
  if ((delivery?.send_unknown_count ?? 0) > 0)
    signals.push({
      id: "unknown",
      tone: "warning",
      title: "Có lượt gửi không xác định",
      detail: "Zalo có thể đã nhận tin; không tự động gửi lại để tránh trùng.",
      value: String(delivery?.send_unknown_count),
    });
  if (
    data.live.total_workers > 0 &&
    data.live.busy_workers >= data.live.total_workers
  )
    signals.push({
      id: "capacity",
      tone: "warning",
      title: "Worker đang dùng hết công suất",
      detail: "Theo dõi hàng đợi để phát hiện áp lực xử lý tăng.",
      value: `${data.live.busy_workers}/${data.live.total_workers}`,
    });
  if (signals.length === 0)
    signals.push({
      id: "stable",
      tone: "success",
      title: "Chưa có tín hiệu cần xử lý",
      detail: "Không ghi nhận bất thường.",
      value: "Ổn định",
    });
  return signals;
};

/** The band's verdict: the worst tone currently active, and why. */
export const deriveVerdict = (signals: Signal[]) => {
  const active = signals.filter((signal) => signal.tone !== "success");
  const tone: Tone = active.some((signal) => signal.tone === "danger")
    ? "danger"
    : active.some((signal) => signal.tone === "warning")
      ? "warning"
      : "success";
  const lead = active[0];
  return {
    tone,
    label:
      tone === "danger"
        ? "Sự cố"
        : tone === "warning"
          ? "Cần chú ý"
          : "Ổn định",
    detail: lead
      ? active.length > 1
        ? `${lead.title} · ${active.length - 1} tín hiệu khác`
        : lead.title
      : "Không ghi nhận bất thường trong khoảng đã chọn.",
  };
};
