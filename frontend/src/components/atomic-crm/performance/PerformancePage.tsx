import { Fragment, useMemo, useState, type ComponentType } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Cpu,
  Database,
  RefreshCw,
  Send,
  Server,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";

import { Button } from "@/components/ui/button";

import {
  type PerfMetrics,
  type PerfSlowTurn,
  type PerfTrendBucket,
  usePerformanceStats,
} from "./usePerformanceStats";
import {
  CANDIDATE_STAGES,
  LANE_LABELS,
  OUTCOME_LABELS,
  STAGE_LABELS,
  STAGE_ORDER,
  STAGE_TARGETS,
  formatCompactDuration as fmtShortMs,
  formatMetricDuration as fmtMs,
  formatStartedAt,
  getSlowTurnTone,
  getStageTone,
  likelyBottleneck,
  type Tone,
} from "../reporting/domain/performanceDiagnostics";
import { formatTrendBucket, getTrendAxisTicks } from "./trendAxis";
import "./performance.css";
const WINDOWS = [
  { key: "1h", label: "1 giờ" },
  { key: "24h", label: "24 giờ" },
  { key: "7d", label: "7 ngày" },
] as const;
type Icon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

const Status = ({ tone, children }: { tone: Tone; children: string }) => {
  const StatusIcon =
    tone === "danger"
      ? AlertCircle
      : tone === "warning"
        ? TriangleAlert
        : tone === "success"
          ? CheckCircle2
          : Activity;
  return (
    <span className={`performance-status is-${tone}`}>
      <StatusIcon aria-hidden="true" />
      {children}
    </span>
  );
};

const Metric = ({
  label,
  value,
  hint,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint: string;
  tone: Tone;
  icon: Icon;
}) => (
  <article className={`performance-metric is-${tone}`}>
    <div className="performance-metric-heading">
      <Icon aria-hidden={true} />
      <p>{label}</p>
    </div>
    <strong>{value}</strong>
    <small>{hint}</small>
  </article>
);

const PerformanceLoading = () => (
  <div
    className="performance-skeletons"
    aria-label="Đang tải số liệu hiệu suất"
  >
    {Array.from({ length: 8 }, (_, index) => (
      <span key={index} className={index > 4 ? "is-panel" : undefined} />
    ))}
  </div>
);

const PerformanceError = ({ onRetry }: { onRetry: () => void }) => {
  const navigate = useNavigate();
  return (
    <section
      className="performance-state tt-alert"
      role="status"
      aria-live="polite"
    >
      <AlertCircle aria-hidden="true" />
      <h2>Không tải được số liệu hiệu suất</h2>
      <p>Kiểm tra kết nối rồi thử lại.</p>
      <div>
        <Button onClick={onRetry}>
          <RefreshCw className="size-4" />
          Thử lại
        </Button>
        <Button variant="outline" onClick={() => navigate("/")}>
          Về Tổng quan
        </Button>
      </div>
    </section>
  );
};

const TrendChart = ({
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
    <section className="performance-panel performance-trend-panel tt-card tt-card-border">
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
        </div>
      </div>
      {trend.length === 0 ? (
        <p className="performance-empty">Chưa có dữ liệu xu hướng.</p>
      ) : (
        <>
          <div
            className="performance-trend"
            role="img"
            aria-label={`Xu hướng độ trễ p95; ${totalErrors} lượt lỗi trong khoảng đã chọn`}
          >
            <span
              className="performance-target-line"
              style={{ bottom: `${Math.min(96, (10_000 / maxP95) * 100)}%` }}
            >
              <b>10 giây</b>
            </span>
            {trend.map((bucket, index) => {
              const height = Math.max(2, ((bucket.p95_ms ?? 0) / maxP95) * 100);
              const tooltip = `${formatTrendBucket(bucket.bucket, true)} · p95 ${fmtMs(bucket.p95_ms)} · ${bucket.turns} lượt · ${bucket.errors} lỗi`;
              return (
                <span
                  className={`performance-trend-bar${bucket.errors > 0 ? " is-error" : ""}`}
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

type Signal = {
  id: string;
  tone: Tone;
  title: string;
  detail: string;
  value: string;
  icon: Icon;
};

const AttentionQueue = ({ data }: { data: PerfMetrics }) => {
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
    <section className="performance-panel performance-attention-panel tt-card tt-card-border">
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
              <b>{signal.value}</b>
              <a
                href="#slow-turns"
                aria-label={`Xem lượt liên quan đến ${signal.title}`}
              >
                <ArrowRight aria-hidden="true" />
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
};

const StageMatrix = ({ data }: { data: PerfMetrics }) => {
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
    <section className="performance-panel performance-matrix tt-card tt-card-border">
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
            <table className="tt-table tt-table-sm">
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

const ADAPTER_LABELS: Record<string, string> = {
  zalo_bot: "Zalo Chatbot",
  zalo_oa: "Zalo OA",
};

const AdapterComparison = ({ data }: { data: PerfMetrics }) => {
  const rows = data.by_adapter ?? [];
  return (
    <section className="performance-panel performance-matrix tt-card tt-card-border">
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
                    <strong>
                      {ADAPTER_LABELS[row.adapter] ?? row.adapter}
                    </strong>
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

const MobileDiagnostics = ({
  candidate,
  internal,
  percentiles,
}: {
  candidate: string[];
  internal: string[];
  percentiles: PerfMetrics["percentiles"];
}) => {
  const [openGroup, setOpenGroup] = useState<"pipeline" | "llm" | null>(
    "pipeline",
  );
  const groups = [
    { id: "pipeline" as const, label: "Pipeline", rows: candidate },
    { id: "llm" as const, label: "LLM & dữ liệu", rows: internal },
  ];

  return (
    <div className="performance-mobile-diagnostics">
      {groups
        .filter((group) => group.rows.length > 0)
        .map((group) => {
          const open = openGroup === group.id;
          return (
            <section key={group.id} className="performance-diagnostic-group">
              <button
                type="button"
                aria-expanded={open}
                onClick={() => setOpenGroup(open ? null : group.id)}
              >
                <span>{group.label}</span>
                <ChevronDown aria-hidden="true" />
              </button>
              {open ? (
                <div className="performance-diagnostic-rows">
                  {group.rows.map((key) => {
                    const stage = percentiles[key];
                    return (
                      <div key={key}>
                        <span>{STAGE_LABELS[key]}</span>
                        <strong>{fmtMs(stage?.p95)}</strong>
                        <small>
                          {STAGE_TARGETS[key] == null
                            ? "Không có mục tiêu"
                            : `Mục tiêu ≤ ${fmtMs(STAGE_TARGETS[key])}`}
                        </small>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </section>
          );
        })}
    </div>
  );
};

const TurnDetail = ({ turn }: { turn: PerfSlowTurn }) => (
  <div className="performance-row-detail">
    <div>
      <strong>Điều phối</strong>
      <p>
        Hàng đợi: <code>{turn.queue_depth ?? "—"}</code> · Chờ slot:{" "}
        <code>{fmtMs(turn.llm_queue_ms)}</code>
      </p>
      <p>
        Độ trễ chưa phân bổ: <code>{fmtMs(turn.dark_time_ms)}</code>
      </p>
    </div>
    <div>
      <strong>LLM & tool</strong>
      <p>
        {turn.llm_calls ?? "—"} lượt LLM · {turn.tool_calls ?? "—"} lượt tool
      </p>
      <p>
        Model: <code>{turn.model_tier ?? "—"}</code>
        {turn.retried_429 ? " · Đã retry 429" : ""}
      </p>
    </div>
    <div>
      <strong>Dữ liệu & token</strong>
      <p>
        DB: <code>{fmtMs(turn.db_ms)}</code> · Tool:{" "}
        <code>{fmtMs(turn.tool_ms)}</code>
      </p>
      <p>
        Prompt: {turn.prompt_tokens ?? "—"} · Completion:{" "}
        {turn.completion_tokens ?? "—"}
      </p>
    </div>
    <div>
      <strong>Trace</strong>
      <p>
        <code>{turn.conversation_id}</code>
      </p>
      <p>Intent: {turn.intent ?? "Chưa có"}</p>
    </div>
  </div>
);

const MobileTurnCard = ({ turn }: { turn: PerfSlowTurn }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [openDetail, setOpenDetail] = useState<string | null>(null);
  const tone = getSlowTurnTone(turn);
  const details = [
    {
      id: "pipeline",
      label: "Pipeline",
      value: `Hàng đợi ${turn.queue_depth ?? "—"} · Chờ slot ${fmtMs(turn.llm_queue_ms)}`,
    },
    {
      id: "llm",
      label: "LLM",
      value: `${turn.llm_calls ?? "—"} lượt · ${turn.tool_calls ?? "—"} tool · ${turn.model_tier ?? "Chưa có model"}`,
    },
    {
      id: "database",
      label: "Dữ liệu",
      value: `DB ${fmtMs(turn.db_ms)} · Tool ${fmtMs(turn.tool_ms)}`,
    },
    {
      id: "trace",
      label: "Trace",
      value: `${turn.conversation_id} · ${turn.intent ?? "Chưa có intent"}`,
    },
    {
      id: "tokens",
      label: "Tokens",
      value: `Prompt ${turn.prompt_tokens ?? "—"} · Completion ${turn.completion_tokens ?? "—"}`,
    },
  ];

  return (
    <article className={`is-${tone}`}>
      <div>
        <Status tone={tone}>
          {tone === "danger"
            ? "Cao"
            : tone === "warning"
              ? "Trung bình"
              : "Thấp"}
        </Status>
        <time>{formatStartedAt(turn.started_at)}</time>
      </div>
      <strong>{fmtMs(turn.total_ms)}</strong>
      <p>{likelyBottleneck(turn)}</p>
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
      >
        {isOpen ? "Thu gọn chi tiết" : "Xem chi tiết"}
        <ChevronRight aria-hidden="true" />
      </button>
      {isOpen ? (
        <div className="performance-mobile-turn-details">
          {details.map((detail) => (
            <section key={detail.id}>
              <button
                type="button"
                aria-expanded={openDetail === detail.id}
                onClick={() =>
                  setOpenDetail((current) =>
                    current === detail.id ? null : detail.id,
                  )
                }
              >
                <span>{detail.label}</span>
                <ChevronDown aria-hidden="true" />
              </button>
              {openDetail === detail.id ? <p>{detail.value}</p> : null}
            </section>
          ))}
        </div>
      ) : null}
    </article>
  );
};

const SlowestTurns = ({ slowTurns }: { slowTurns: PerfSlowTurn[] }) => {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  return (
    <section
      className="performance-panel performance-slow-turns tt-card tt-card-border"
      id="slow-turns"
    >
      <div className="performance-section-heading">
        <div>
          <h2>
            Lượt cần xem <span>{slowTurns.length}</span>
          </h2>
          <p>Các lượt ảnh hưởng tới phản hồi hoặc giao gửi.</p>
        </div>
      </div>
      {slowTurns.length === 0 ? (
        <p className="performance-empty">
          Chưa có lượt cần xem trong khoảng này.
        </p>
      ) : (
        <>
          <div
            className="performance-table-wrap"
            role="region"
            aria-label="Bảng lượt cần xem"
            tabIndex={0}
          >
            <table className="tt-table tt-table-sm">
              <thead>
                <tr>
                  <th>Mức độ</th>
                  <th>Thời gian</th>
                  <th>Tổng</th>
                  <th>Nút thắt nhiều khả năng</th>
                  <th>Luồng</th>
                  <th>Kết quả giao gửi</th>
                  <th aria-label="Mở rộng" />
                </tr>
              </thead>
              <tbody>
                {slowTurns.map((turn) => {
                  const tone = getSlowTurnTone(turn);
                  const isOpen = expandedId === turn.id;
                  return (
                    <Fragment key={turn.id}>
                      <tr className={isOpen ? "is-open" : undefined}>
                        <td>
                          <Status tone={tone}>
                            {tone === "danger"
                              ? "Cao"
                              : tone === "warning"
                                ? "Trung bình"
                                : "Thấp"}
                          </Status>
                        </td>
                        <td>{formatStartedAt(turn.started_at)}</td>
                        <td>
                          <b>{fmtMs(turn.total_ms)}</b>
                        </td>
                        <td>{likelyBottleneck(turn)}</td>
                        <td>
                          {LANE_LABELS[turn.lane ?? ""] ??
                            turn.lane ??
                            "Không rõ"}
                        </td>
                        <td>
                          <Status
                            tone={
                              turn.outcome === "ERROR" ? "danger" : "success"
                            }
                          >
                            {OUTCOME_LABELS[turn.outcome] ??
                              turn.outcome ??
                              "Không rõ"}
                          </Status>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="performance-expand"
                            aria-expanded={isOpen}
                            aria-label={
                              isOpen ? "Thu gọn chi tiết" : "Mở rộng chi tiết"
                            }
                            onClick={() =>
                              setExpandedId(isOpen ? null : turn.id)
                            }
                          >
                            {isOpen ? (
                              <ChevronDown className="size-4" />
                            ) : (
                              <ChevronRight className="size-4" />
                            )}
                          </button>
                        </td>
                      </tr>
                      {isOpen ? (
                        <tr className="performance-detail-row">
                          <td colSpan={7}>
                            <TurnDetail turn={turn} />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="performance-turn-cards">
            {slowTurns.map((turn) => (
              <MobileTurnCard key={turn.id} turn={turn} />
            ))}
          </div>
        </>
      )}
    </section>
  );
};

const SupportingStats = ({ data }: { data: PerfMetrics }) => {
  const total = Object.values(data.by_outcome).reduce(
    (sum, value) => sum + value,
    0,
  );
  const sent = data.by_outcome.SENT ?? 0;
  const sendRate = total > 0 ? `${Math.round((sent / total) * 100)}%` : "—";
  const lanes = Object.entries(data.by_lane).sort(([, a], [, b]) => b - a);
  return (
    <section className="performance-supporting" aria-label="Chỉ số hỗ trợ">
      <article>
        <div>
          <Send aria-hidden="true" />
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
          <Activity aria-hidden="true" />
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
          <Database aria-hidden="true" />
          <h2>Độ đầy đủ dữ liệu</h2>
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

const PerformanceMetrics = ({ data }: { data: PerfMetrics }) => {
  const endToEnd = data.percentiles.end_to_end?.p95;
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
          value={Object.values(data.by_outcome)
            .reduce((sum, value) => sum + value, 0)
            .toLocaleString()}
          hint={`trong ${data.window === "1h" ? "1 giờ" : data.window === "7d" ? "7 ngày" : "24 giờ"}`}
          tone="neutral"
          icon={Activity}
        />
      </section>
      <section className="performance-primary-grid">
        <TrendChart trend={data.trend ?? []} window={data.window} />
        <AttentionQueue data={data} />
      </section>
      <StageMatrix data={data} />
      <AdapterComparison data={data} />
      <SlowestTurns slowTurns={data.slow_turns} />
      <SupportingStats data={data} />
    </>
  );
};

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
