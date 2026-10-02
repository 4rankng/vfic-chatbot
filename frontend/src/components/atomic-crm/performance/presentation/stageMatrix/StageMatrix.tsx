import {
  CANDIDATE_STAGES,
  STAGE_LABELS,
  STAGE_ORDER,
  STAGE_TARGETS,
  formatMetricDuration as fmtMs,
  getStageTone,
} from "../../../reporting/domain/performanceDiagnostics";
import type { PerfMetrics } from "../../usePerformanceStats";
import { Status } from "../primitives";
import { MobileDiagnostics } from "./MobileDiagnostics";

/**
 * "Chẩn đoán độ trễ" — p50/p95/p99 per measurement point, split into the
 * stages the candidate actually waits on and the internal diagnostic stages.
 */
export const StageMatrix = ({ data }: { data: PerfMetrics }) => {
  const percentiles = data.percentiles ?? {};
  const rows = STAGE_ORDER.filter(
    (key) =>
      percentiles[key]?.p50 != null ||
      percentiles[key]?.p95 != null ||
      percentiles[key]?.p99 != null,
  );
  const renderRow = (key: string) => {
    const stage = percentiles[key];
    const tone = getStageTone(key, stage?.p95);
    const target = STAGE_TARGETS[key];
    const callsP95 = percentiles.llm_calls_per?.p95;
    return (
      <tr key={key}>
        <td>
          <strong>{STAGE_LABELS[key]}</strong>
          {key === "llm_model" && callsP95 != null ? (
            <small>~{callsP95} lượt/turn — cộng dồn</small>
          ) : key === "end_to_end" ? (
            <small>Độ trễ ứng viên thực sự chờ</small>
          ) : null}
        </td>
        <td>{fmtMs(stage?.p50)}</td>
        <td>
          <b>{fmtMs(stage?.p95)}</b>
        </td>
        <td>{fmtMs(stage?.p99)}</td>
        <td>{target == null ? "—" : `≤ ${fmtMs(target)}`}</td>
        <td>
          <Status tone={tone}>
            {tone === "danger"
              ? "Vượt ngưỡng"
              : tone === "warning"
                ? "Cần cải thiện"
                : tone === "success"
                  ? "Đạt"
                  : "Chưa có mục tiêu"}
          </Status>
        </td>
      </tr>
    );
  };
  const candidate = rows.filter((key) => CANDIDATE_STAGES.has(key));
  const internal = rows.filter((key) => !CANDIDATE_STAGES.has(key));
  return (
    <section className="performance-panel performance-matrix">
      <div className="performance-section-heading">
        <div>
          <h2>Chẩn đoán độ trễ</h2>
          <p>p50 · p95 · p99 theo từng điểm đo, không cộng dồn.</p>
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="performance-empty">
          Chưa có lượt xử lý nào để phân tích độ trễ.
        </p>
      ) : (
        <>
          <div
            className="performance-table-wrap"
            role="region"
            aria-label="Bảng chẩn đoán độ trễ"
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th>Giai đoạn</th>
                  <th>p50</th>
                  <th>p95</th>
                  <th>p99</th>
                  <th>Mục tiêu</th>
                  <th>Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {candidate.length > 0 ? (
                  <tr className="performance-group-row">
                    <th colSpan={6}>Chờ ứng viên</th>
                  </tr>
                ) : null}
                {candidate.map(renderRow)}
                {internal.length > 0 ? (
                  <tr className="performance-group-row">
                    <th colSpan={6}>Chẩn đoán nội bộ</th>
                  </tr>
                ) : null}
                {internal.map(renderRow)}
              </tbody>
            </table>
          </div>
          <MobileDiagnostics
            candidate={candidate}
            internal={internal}
            percentiles={percentiles}
          />
        </>
      )}
    </section>
  );
};
