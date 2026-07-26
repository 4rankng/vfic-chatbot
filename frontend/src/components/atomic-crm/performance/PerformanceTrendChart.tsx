import { TriangleAlert } from "lucide-react";

import { formatMetricDuration as fmtMs } from "../reporting/domain/performanceDiagnostics";
import { formatTrendBucket, getTrendAxisTicks } from "./trendAxis";
import type { PerfMetrics, PerfTrendBucket } from "./usePerformanceStats";

export const PerformanceTrendChart = ({
  trend,
  window,
}: {
  trend: PerfTrendBucket[];
  window: PerfMetrics["window"];
}) => {
  const maxP95 = Math.max(10_000, ...trend.map((bucket) => bucket.p95_ms ?? 0));
  const totalErrors = trend.reduce((sum, bucket) => sum + bucket.errors, 0);
  const axisTicks = getTrendAxisTicks(trend, window === "7d");

  return (
    <section className="performance-panel performance-trend-panel">
      <div className="performance-section-heading">
        <div>
          <h2>Xu hướng độ trễ ứng viên chờ</h2>
          <p>p95 mỗi 5 phút · mục tiêu ≤ 10 giây.</p>
        </div>
        <div className="performance-legend" aria-label="Chú giải biểu đồ">
          <span>
            <i className="is-line" />
            p95
          </span>
          <span>
            <i className="is-target" />
            Mục tiêu 10 giây
          </span>
          <span>
            <i className="is-tone is-success" />
            &lt; 10 giây
          </span>
          <span>
            <i className="is-tone is-warning" />
            10–20 giây
          </span>
          <span>
            <i className="is-tone" />≥ 20 giây
          </span>
        </div>
      </div>
      {trend.length === 0 ? (
        <p className="performance-empty">Chưa có dữ liệu xu hướng.</p>
      ) : (
        <>
          <table className="sr-only" id="performance-trend-data">
            <caption>Dữ liệu xu hướng độ trễ ứng viên chờ</caption>
            <thead>
              <tr>
                <th scope="col">Mốc thời gian</th>
                <th scope="col">p95</th>
                <th scope="col">Số lượt</th>
                <th scope="col">Lỗi</th>
              </tr>
            </thead>
            <tbody>
              {trend.map((bucket, index) => (
                <tr key={`${bucket.bucket ?? index}-data`}>
                  <th scope="row">{formatTrendBucket(bucket.bucket, true)}</th>
                  <td>{fmtMs(bucket.p95_ms)}</td>
                  <td>{bucket.turns} lượt</td>
                  <td>{bucket.errors} lỗi</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div
            className="performance-trend"
            role="img"
            aria-label={`Xu hướng độ trễ p95; ${totalErrors} lượt lỗi trong khoảng đã chọn`}
            aria-describedby="performance-trend-data"
          >
            <span className="performance-target-label" aria-hidden="true">
              10 giây
            </span>
            <span
              className="performance-target-line"
              style={{ bottom: `${Math.min(96, (10_000 / maxP95) * 100)}%` }}
            />
            {trend.map((bucket, index) => {
              const height = Math.max(2, ((bucket.p95_ms ?? 0) / maxP95) * 100);
              const p95 = bucket.p95_ms;
              const toneClass =
                bucket.errors > 0
                  ? " is-error"
                  : p95 == null
                    ? ""
                    : p95 < 10_000
                      ? " is-success"
                      : p95 < 20_000
                        ? " is-warning"
                        : "";
              const tooltip = `${formatTrendBucket(bucket.bucket, true)} · p95 ${fmtMs(bucket.p95_ms)} · ${bucket.turns} lượt · ${bucket.errors} lỗi`;

              return (
                <span
                  className={`performance-trend-bar${toneClass}`}
                  key={`${bucket.bucket ?? index}`}
                  style={{ height: `${height}%` }}
                  title={tooltip}
                  aria-label={tooltip}
                />
              );
            })}
          </div>
          <div className="performance-trend-axis" aria-hidden="true">
            {axisTicks.map((tick) => (
              <span
                key={tick.index}
                style={{
                  left: `${trend.length > 1 ? (tick.index / (trend.length - 1)) * 100 : 0}%`,
                }}
                className={
                  tick.index === 0
                    ? "is-first"
                    : tick.index === trend.length - 1
                      ? "is-last"
                      : ""
                }
              >
                {tick.label}
              </span>
            ))}
          </div>
          <p className="performance-chart-note">
            <TriangleAlert aria-hidden="true" />{" "}
            {totalErrors > 0
              ? `${totalErrors} lượt lỗi cần đối chiếu với các phiên vượt ngưỡng.`
              : "Không ghi nhận lượt lỗi trong khoảng đã chọn."}
          </p>
        </>
      )}
    </section>
  );
};
