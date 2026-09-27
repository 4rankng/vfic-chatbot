import { useMemo, useState } from "react";
import {
  Activity,
  ChevronDown,
  Clock3,
  Cpu,
  RefreshCw,
  Send,
  Server,
  ShieldAlert,
} from "lucide-react";

import {
  formatMetricDuration as fmtMs,
  getStageTone,
  type Tone,
} from "../reporting/domain/performanceDiagnostics";
import { PerformanceTrendChart } from "./PerformanceTrendChart";
import { AttentionQueue } from "./presentation/attentionQueue/AttentionQueue";
import { AdapterComparison } from "./presentation/adapterComparison/AdapterComparison";
import { Metric } from "./presentation/primitives";
import {
  PerformanceError,
  PerformanceLoading,
  PerformanceNoActivity,
} from "./presentation/pageStates";
import { SlowestTurns } from "./presentation/slowestTurns/SlowestTurns";
import { StageMatrix } from "./presentation/stageMatrix/StageMatrix";
import { SupportingStats } from "./presentation/supportingStats/SupportingStats";
import { type PerfMetrics, usePerformanceStats } from "./usePerformanceStats";
import "./performance.css";

const WINDOWS = [
  { key: "1h", label: "1 giờ" },
  { key: "24h", label: "24 giờ" },
  { key: "7d", label: "7 ngày" },
] as const;

/**
 * Composition root for the performance dashboard: it owns the live-status
 * strip, decides which windows the selected time range can show, and places
 * the five reporting windows. Every window itself lives under
 * `presentation/<window>/`.
 */
export const PerformanceMetrics = ({ data }: { data: PerfMetrics }) => {
  const endToEnd = data.percentiles.end_to_end?.p95;
  const totalTurns = Object.values(data.by_outcome).reduce(
    (sum, value) => sum + value,
    0,
  );
  const hasPercentileData = Object.values(data.percentiles).some(
    (stage) => stage.p50 != null || stage.p95 != null || stage.p99 != null,
  );
  const hasHistoricalData =
    totalTurns > 0 ||
    data.trend.length > 0 ||
    data.slow_turns.length > 0 ||
    hasPercentileData ||
    (data.by_adapter ?? []).some((adapter) => adapter.turns > 0);
  const windowLabel =
    data.window === "1h" ? "1 giờ" : data.window === "7d" ? "7 ngày" : "24 giờ";
  const workerTone: Tone =
    data.live.total_workers > 0 &&
    data.live.busy_workers >= data.live.total_workers
      ? "warning"
      : "success";
  const deliveryTone: Tone =
    (data.reliability?.failed_count ?? 0) > 0
      ? "danger"
      : (data.reliability?.send_unknown_count ?? 0) > 0
        ? "warning"
        : "success";
  return (
    <>
      <section className="performance-metrics" aria-label="Tình trạng hệ thống">
        <Metric
          label="Hàng đợi"
          value={String(data.live.queue_depth)}
          hint="webhook đang chờ"
          tone={data.live.queue_depth > 0 ? "warning" : "neutral"}
          icon={Server}
        />
        <Metric
          label="Sức chứa worker"
          value={`${data.live.busy_workers}/${data.live.total_workers}`}
          hint="worker đang bận"
          tone={workerTone}
          icon={Cpu}
        />
        <Metric
          label="Độ trễ p95"
          value={fmtMs(endToEnd)}
          hint="tổng từ webhook · mục tiêu ≤ 10 giây"
          tone={getStageTone("end_to_end", endToEnd)}
          icon={Clock3}
        />
        <Metric
          label="LLM 429"
          value={String(data.live.minimax_429s_last_1m)}
          hint="trong 1 phút gần nhất"
          tone={data.live.minimax_429s_last_1m > 0 ? "warning" : "success"}
          icon={ShieldAlert}
        />
        <Metric
          label="Giao gửi rủi ro"
          value={String(
            (data.reliability?.failed_count ?? 0) +
              (data.reliability?.send_unknown_count ?? 0),
          )}
          hint="thất bại + không xác định"
          tone={deliveryTone}
          icon={Send}
        />
        <Metric
          label="Lượt xử lý"
          value={totalTurns.toLocaleString()}
          hint={`trong ${windowLabel}`}
          tone="neutral"
          icon={Activity}
        />
      </section>
      {!hasHistoricalData ? (
        <PerformanceNoActivity windowLabel={windowLabel} />
      ) : (
        <>
          <section className="performance-primary-grid">
            <PerformanceTrendChart
              trend={data.trend ?? []}
              window={data.window}
            />
            <AttentionQueue data={data} />
          </section>
          {data.slow_turns.length > 0 ? (
            <SlowestTurns slowTurns={data.slow_turns} />
          ) : null}
          <details className="performance-details">
            <summary>
              <span>
                <strong>Phân tích chi tiết</strong>
                <small>Giai đoạn · kênh · dữ liệu hỗ trợ</small>
              </span>
              <ChevronDown aria-hidden="true" />
            </summary>
            <div className="performance-details-content">
              {hasPercentileData ? <StageMatrix data={data} /> : null}
              {(data.by_adapter ?? []).length > 0 ? (
                <AdapterComparison data={data} />
              ) : null}
              <SupportingStats data={data} />
            </div>
          </details>
        </>
      )}
    </>
  );
};

/** Page shell: time-range switcher, manual refresh, and the three load states. */
const PerformancePanel = () => {
  const [windowKey, setWindowKey] = useState<"1h" | "24h" | "7d">("24h");
  const { data, isPending, isError, refetch, dataUpdatedAt } =
    usePerformanceStats(windowKey);
  const freshness = useMemo(
    () =>
      dataUpdatedAt
        ? new Intl.DateTimeFormat("vi-VN", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }).format(dataUpdatedAt)
        : null,
    [dataUpdatedAt],
  );
  const hasError = isError || !data;
  return (
    <div className="performance-page" aria-busy={isPending || undefined}>
      <header className="performance-header">
        <div>
          <p className="performance-kicker">Vận hành</p>
          <h1>Hiệu suất chatbot</h1>
          <p>
            {isPending
              ? "Đang tải số liệu cho khoảng thời gian đã chọn."
              : "Trải nghiệm ứng viên, năng lực xử lý và độ tin cậy giao gửi."}
          </p>
        </div>
        <div className="performance-header-actions">
          <div className="performance-window" aria-label="Khoảng thời gian">
            {WINDOWS.map((window) => (
              <button
                key={window.key}
                type="button"
                aria-pressed={windowKey === window.key}
                onClick={() => setWindowKey(window.key)}
              >
                {window.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="performance-refresh"
            onClick={() => void refetch()}
            disabled={isPending}
            aria-label={
              freshness ? `Cập nhật lúc ${freshness}` : "Cập nhật dữ liệu"
            }
          >
            <RefreshCw
              className={isPending ? "is-spinning" : undefined}
              aria-hidden="true"
            />
            {freshness ? (
              <>
                <span className="performance-refresh-prefix">
                  Cập nhật lúc{" "}
                </span>
                {freshness}
              </>
            ) : (
              "Cập nhật"
            )}
          </button>
        </div>
      </header>
      {isPending ? <PerformanceLoading /> : null}
      {!isPending && hasError ? (
        <PerformanceError onRetry={() => void refetch()} />
      ) : null}
      {!isPending && !hasError && data ? (
        <PerformanceMetrics data={data} />
      ) : null}
    </div>
  );
};

export const PerformancePage = () => <PerformancePanel />;
