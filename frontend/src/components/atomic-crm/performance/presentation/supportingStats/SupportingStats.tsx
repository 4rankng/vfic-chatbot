import { Dataflow01, Database01, Send01, Zap } from "@untitledui/icons";

import { LANE_LABELS } from "../../../reporting/domain/performanceDiagnostics";
import type { PerfMetrics } from "../../usePerformanceStats";

const formatTokenTotal = (value: number): string => {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
};

/**
 * Closing strip of the detail window: delivery reliability, lane mix and how
 * much trend data backs the page.
 */
export const SupportingStats = ({ data }: { data: PerfMetrics }) => {
  const total = Object.values(data.by_outcome).reduce(
    (sum, value) => sum + value,
    0,
  );
  const sent = data.by_outcome.SENT ?? 0;
  const sendRate = total > 0 ? `${Math.round((sent / total) * 100)}%` : "—";
  const lanes = Object.entries(data.by_lane).sort(([, a], [, b]) => b - a);
  const quality = data.quality;
  const tokensTotal =
    (quality?.prompt_tokens_total ?? 0) +
    (quality?.completion_tokens_total ?? 0);
  return (
    <section className="performance-supporting" aria-label="Chỉ số hỗ trợ">
      <article>
        <div>
          <Send01 aria-hidden="true" />
          <h2>Độ tin cậy giao gửi</h2>
        </div>
        <strong>{sendRate}</strong>
        <p>
          {sent.toLocaleString()} đã gửi · {data.reliability?.failed_count ?? 0}{" "}
          thất bại · {data.reliability?.send_unknown_count ?? 0} không xác định
        </p>
      </article>
      <article>
        <div>
          <Dataflow01 aria-hidden="true" />
          <h2>Phân bố theo lane</h2>
        </div>
        {lanes.length === 0 ? (
          <p>Chưa có dữ liệu.</p>
        ) : (
          <ul>
            {lanes.slice(0, 3).map(([lane, value]) => (
              <li key={lane}>
                <span>{LANE_LABELS[lane] ?? lane}</span>
                <b>{value.toLocaleString()}</b>
              </li>
            ))}
          </ul>
        )}
      </article>
      <article>
        <div>
          <Zap aria-hidden="true" />
          <h2>Chất lượng xử lý</h2>
        </div>
        <strong>{quality?.prompt_cache_hit_rate ?? "—"}% cache</strong>
        <p>
          {quality?.degraded_count ?? 0} lượt suy giảm ·{" "}
          {quality?.retried_429_count ?? 0} lượt retry 429
        </p>
        <ul>
          <li>
            <span>Token prompt + completion</span>
            <b>{formatTokenTotal(tokensTotal)}</b>
          </li>
          <li>
            <span>Token từ cache</span>
            <b>{formatTokenTotal(quality?.cached_tokens_total ?? 0)}</b>
          </li>
        </ul>
      </article>
      <article>
        <div>
          <Database01 aria-hidden="true" />
          <h2>Dữ liệu</h2>
        </div>
        <strong>{data.trend.length > 0 ? "Có dữ liệu" : "Chưa đủ"}</strong>
        <p>
          {data.trend.length > 0
            ? `${data.trend.length} điểm xu hướng trong khoảng đã chọn.`
            : "Chưa có điểm thời gian để kiểm tra."}
        </p>
      </article>
    </section>
  );
};
