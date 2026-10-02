import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  Cpu,
  Send,
  Server,
  ShieldAlert,
} from "lucide-react";

import {
  STAGE_TARGETS,
  formatMetricDuration as fmtMs,
  getStageTone,
  type Tone,
} from "../../../reporting/domain/performanceDiagnostics";
import type { PerfMetrics } from "../../usePerformanceStats";
import type { Icon } from "../primitives";

type Signal = {
  id: string;
  tone: Tone;
  title: string;
  detail: string;
  value: string;
  icon: Icon;
};

/**
 * "Tín hiệu cần xử lý" — the one window that stays above the fold. It ranks
 * live p95 latency, LLM rate limiting, delivery outcomes and worker saturation
 * into a single ordered queue, falling back to a calm "nothing to do" state.
 */
export const AttentionQueue = ({ data }: { data: PerfMetrics }) => {
  const showRelatedTurns = () => {
    const target = document.getElementById("slow-turns");
    if (!target) return;
    target.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
      block: "start",
    });
    target.focus({ preventScroll: true });
  };
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
      icon: Clock3,
    });
  if (data.live.minimax_429s_last_1m > 0)
    signals.push({
      id: "rate-limit",
      tone: "warning",
      title: "LLM có phản hồi 429",
      detail: "Đã có retry hoặc nguy cơ làm chậm các lượt mới.",
      value: `${data.live.minimax_429s_last_1m} trong 1 phút`,
      icon: Cpu,
    });
  if ((delivery?.failed_count ?? 0) > 0)
    signals.push({
      id: "failed",
      tone: "danger",
      title: "Có lượt gửi thất bại",
      detail: "Kiểm tra các lượt chậm để xác nhận việc giao tin nhắn.",
      value: String(delivery?.failed_count),
      icon: Send,
    });
  if ((delivery?.send_unknown_count ?? 0) > 0)
    signals.push({
      id: "unknown",
      tone: "warning",
      title: "Có lượt gửi không xác định",
      detail: "Zalo có thể đã nhận tin; không tự động gửi lại để tránh trùng.",
      value: String(delivery?.send_unknown_count),
      icon: ShieldAlert,
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
      icon: Server,
    });
  if (signals.length === 0)
    signals.push({
      id: "stable",
      tone: "success",
      title: "Chưa có tín hiệu cần xử lý",
      detail: "Không ghi nhận bất thường.",
      value: "Ổn định",
      icon: CheckCircle2,
    });
  return (
    <section className="performance-panel performance-attention-panel">
      <div className="performance-section-heading">
        <div>
          <h2>
            Tín hiệu cần xử lý{" "}
            <span>
              {signals.filter((signal) => signal.tone !== "success").length}
            </span>
          </h2>
          <p>Ưu tiên theo ảnh hưởng tới ứng viên.</p>
        </div>
      </div>
      <ul className="performance-signal-list">
        {signals.slice(0, 5).map((signal) => {
          const SignalIcon = signal.icon;
          return (
            <li key={signal.id} className={`is-${signal.tone}`}>
              <SignalIcon aria-hidden={true} />
              <div>
                <strong>{signal.title}</strong>
                <small>{signal.detail}</small>
              </div>
              {signal.tone === "success" ? null : (
                <>
                  <b>{signal.value}</b>
                  {data.slow_turns.length > 0 ? (
                    <button
                      type="button"
                      aria-label={`Xem lượt liên quan đến ${signal.title}`}
                      onClick={showRelatedTurns}
                    >
                      <ArrowRight aria-hidden="true" />
                    </button>
                  ) : null}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
};
