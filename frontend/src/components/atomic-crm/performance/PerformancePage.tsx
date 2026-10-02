import { useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart03,
  CheckCircle,
  ChevronDown,
  ClockRefresh,
  CpuChip01,
  Send01,
  Server01,
} from "@untitledui/icons";

import {
  formatMetricDuration as fmtMs,
  type Tone,
} from "../reporting/domain/performanceDiagnostics";
import {
  ButtonGroup,
  ButtonGroupItem,
} from "@/components/base/button-group/button-group";
import { Button } from "@/components/base/buttons/button";
import { PerformanceTrendChart } from "./PerformanceTrendChart";
import { AttentionQueue } from "./presentation/attentionQueue/AttentionQueue";
import { AdapterComparison } from "./presentation/adapterComparison/AdapterComparison";
import { Metric, Status } from "./presentation/primitives";
import {
  PerformanceError,
  PerformanceLoading,
  PerformanceNoActivity,
} from "./presentation/pageStates";
import { SlowestTurns } from "./presentation/slowestTurns/SlowestTurns";
import { StageMatrix } from "./presentation/stageMatrix/StageMatrix";
import { SupportingStats } from "./presentation/supportingStats/SupportingStats";
import { collectSignals, deriveVerdict } from "./presentation/signals";
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
  const endToEndP50 = data.percentiles.end_to_end?.p50;
  const totalTurns = Object.values(data.by_outcome).reduce(
    (sum, value) => sum + value,
    0,
  );
  const sentTurns = data.by_outcome.SENT ?? 0;
  const successRate =
    totalTurns > 0 ? Math.round((sentTurns / totalTurns) * 100) : null;
  const successTone: Tone =
    successRate == null
      ? "neutral"
      : successRate >= 98
        ? "success"
        : successRate >= 90
          ? "warning"
          : "danger";
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
    data.live.total_workers === 0
      ? "neutral"
      : data.live.busy_workers >= data.live.total_workers
        ? "warning"
        : "success";
  const deliveryTone: Tone =
    (data.reliability?.failed_count ?? 0) > 0
      ? "danger"
      : (data.reliability?.send_unknown_count ?? 0) > 0
        ? "warning"
        : "success";
  const verdict = deriveVerdict(collectSignals(data));
  return (
    <>
      <section
        className={`performance-band is-${verdict.tone}`}
        aria-label="Đánh giá tổng quan"
      >
        <div className="performance-band-verdict">
          <Status tone={verdict.tone}>{verdict.label}</Status>
          <p>{verdict.detail}</p>
        </div>
        <div className="performance-band-metric">
          <p>Độ trễ p95</p>
          <strong>{fmtMs(endToEnd)}</strong>
          <small>
            {endToEndP50 != null ? `p50 ${fmtMs(endToEndP50)} · ` : ""}
            mục tiêu p95 ≤ 10 giây
          </small>
        </div>
      </section>
      <section className="performance-metrics" aria-label="Tình trạng hệ thống">
        <Metric
          label="Hàng đợi"
          value={String(data.live.queue_depth)}
          hint="webhook đang chờ"
          tone={data.live.queue_depth > 0 ? "warning" : "neutral"}
          icon={Server01}
        />
        <Metric
          label="Mức tải worker"
          value={
            data.live.total_workers > 0
              ? `${data.live.busy_workers}/${data.live.total_workers}`
              : "Chưa có"
          }
          hint={
            data.live.total_workers > 0
              ? "worker đang bận"
              : "chưa ghi nhận worker"
          }
          tone={workerTone}
          icon={CpuChip01}
          meter={
            data.live.total_workers > 0
              ? (data.live.busy_workers / data.live.total_workers) * 100
              : undefined
          }
        />
        <Metric
          label="LLM 429"
          value={String(data.live.minimax_429s_last_1m)}
          hint="trong 1 phút gần nhất"
          tone={data.live.minimax_429s_last_1m > 0 ? "warning" : "success"}
          icon={AlertTriangle}
        />
        <Metric
          label="Gửi tin cần kiểm tra"
          value={String(
            (data.reliability?.failed_count ?? 0) +
              (data.reliability?.send_unknown_count ?? 0),
          )}
          hint="thất bại + không xác định"
          tone={deliveryTone}
          icon={Send01}
        />
        <Metric
          label="Tỷ lệ thành công"
          value={successRate == null ? "—" : `${successRate}%`}
          hint="lượt gửi thành công"
          tone={successTone}
          icon={CheckCircle}
        />
        <Metric
          label="Lượt xử lý"
          value={totalTurns.toLocaleString()}
          hint={`trong ${windowLabel}`}
          tone="neutral"
          icon={BarChart03}
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
  const { data, isPending, isFetching, isError, refetch, dataUpdatedAt } =
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
  const hasError = !data;
  const refreshing = Boolean(isPending || isFetching);
  return (
    <div className="performance-page" aria-busy={refreshing || undefined}>
      <header className="performance-header">
        <div>
          <h1>Hiệu suất chatbot</h1>
          <p>
            {isPending
              ? "Đang tải số liệu cho khoảng thời gian đã chọn."
              : "Độ trễ xử lý, mức tải và trạng thái gửi tin theo từng kênh."}
          </p>
        </div>
        <div className="performance-header-actions">
          <ButtonGroup
            size="sm"
            className="performance-window-switcher uu-scope"
            aria-label="Khoảng thời gian"
            selectedKeys={[windowKey]}
            onSelectionChange={(keys) => {
              const next = [...keys][0];
              if (next) setWindowKey(next as (typeof WINDOWS)[number]["key"]);
            }}
          >
            {WINDOWS.map((window) => (
              <ButtonGroupItem
                key={window.key}
                id={window.key}
                className="performance-window-option"
              >
                {window.label}
              </ButtonGroupItem>
            ))}
          </ButtonGroup>
          <Button
            type="button"
            color="secondary"
            size="sm"
            className="performance-refresh"
            onClick={() => void refetch()}
            isDisabled={refreshing}
            aria-label={
              freshness ? `Cập nhật lúc ${freshness}` : "Cập nhật dữ liệu"
            }
            iconLeading={
              <ClockRefresh
                className={refreshing ? "is-spinning" : undefined}
                aria-hidden={true}
              />
            }
          >
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
          </Button>
        </div>
      </header>
      {data && isError ? (
        <div className="performance-stale-notice" role="alert">
          Chưa cập nhật được số liệu. Dữ liệu lần tải trước vẫn hiển thị; chọn
          Cập nhật để thử lại.
        </div>
      ) : null}
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
