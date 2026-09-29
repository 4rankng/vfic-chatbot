import { formatCompactDuration as fmtShortMs } from "../../../reporting/domain/performanceDiagnostics";
import { conversationChannelLabel } from "../../../conversations/domain/channel-labels";
import type { PerfMetrics } from "../../usePerformanceStats";

/**
 * "So sánh kênh giao gửi" — per-channel delivery, timed to the moment the
 * provider accepted the request rather than the moment the candidate saw it.
 *
 * The channel name comes from `conversations/domain/channel-labels`, the single
 * map every channel-naming surface reads, so this matrix and the inbox can never
 * label the same provider two different ways.
 */
export const AdapterComparison = ({ data }: { data: PerfMetrics }) => {
  const rows = data.by_adapter ?? [];
  return (
    <section className="performance-panel performance-matrix">
      <div className="performance-section-heading">
        <div>
          <h2>So sánh kênh giao gửi</h2>
          <p>
            Đo đến khi nhà cung cấp nhận yêu cầu, chưa phải lúc ứng viên thấy
            tin.
          </p>
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="performance-empty">Chưa có dữ liệu theo kênh.</p>
      ) : (
        <div
          className="performance-table-wrap"
          role="region"
          aria-label="So sánh kênh giao gửi"
          tabIndex={0}
        >
          <table className="tt-table tt-table-sm">
            <thead>
              <tr>
                <th>Kênh</th>
                <th>Lượt gửi</th>
                <th>Provider p50 / p95</th>
                <th>Tổng từ webhook p50 / p95</th>
                <th>Retry / refresh</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.adapter}>
                  <td>
                    <strong>{conversationChannelLabel(row.adapter)}</strong>
                  </td>
                  <td>
                    {row.sent}/{row.turns}
                  </td>
                  <td>
                    {fmtShortMs(row.provider_p50_ms)} /{" "}
                    {fmtShortMs(row.provider_p95_ms)}
                  </td>
                  <td>
                    {fmtShortMs(row.end_to_end_p50_ms)} /{" "}
                    {fmtShortMs(row.end_to_end_p95_ms)}
                  </td>
                  <td>
                    {row.retry_count} / {row.refresh_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};
