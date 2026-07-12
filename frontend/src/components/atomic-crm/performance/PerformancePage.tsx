import { Fragment, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertCircle, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

import {
  type PerfMetrics,
  type PerfSlowTurn,
  type PerfTrendBucket,
  usePerformanceStats,
} from "./usePerformanceStats";
import { formatTrendBucket, getTrendAxisTicks } from "./trendAxis";
import "./performance.css";

const STAGE_LABELS: Record<string, string> = {
  webhook_to_pickup: "Webhook → nhận việc",
  preamble: "Khởi tạo",
  lead: "Lấy hồ sơ ứng viên",
  system_prompt: "Xây prompt hệ thống",
  faq_bypass: "FAQ bypass",
  llm_queue: "LLM — chờ slot",
  llm_model: "LLM — xử lý model",
  db: "Cơ sở dữ liệu",
  send: "Gửi Zalo",
  total: "Xử lý sau khởi tạo",
  end_to_end: "Tổng từ webhook",
};
const LANE_LABELS: Record<string, string> = {
  agent: "Agent (LLM)",
  fast_lane: "Fast lane",
  faq_bypass: "FAQ bypass",
  unknown: "Không rõ",
};
const OUTCOME_LABELS: Record<string, string> = {
  SENT: "Đã gửi",
  SUPPRESSED: "Đã chặn",
  ERROR: "Lỗi xử lý",
};
const STAGE_ORDER = [
  "webhook_to_pickup",
  "preamble",
  "lead",
  "system_prompt",
  "faq_bypass",
  "llm_queue",
  "llm_model",
  "db",
  "send",
  "total",
  "end_to_end",
];
const WINDOWS = [
  { key: "1h", label: "1 giờ" },
  { key: "24h", label: "24 giờ" },
  { key: "7d", label: "7 ngày" },
] as const;

const fmtMs = (value: number | null | undefined): string =>
  value == null
    ? "Chưa có"
    : value >= 1000
      ? `${(value / 1000).toFixed(1)} giây`
      : `${value} ms`;

const Metric = ({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "success" | "warning";
}) => (
  <article className={`performance-metric is-${tone}`}>
    <p>{label}</p>
    <strong>{value}</strong>
    {hint ? <small>{hint}</small> : null}
  </article>
);

const PerformanceLoading = () => (
  <div
    className="performance-skeletons"
    aria-label="Đang tải số liệu hiệu suất"
  >
    {Array.from({ length: 8 }, (_, index) => (
      <span key={index} className={index > 3 ? "is-panel" : undefined} />
    ))}
  </div>
);

const PerformanceError = ({ onRetry }: { onRetry: () => void }) => {
  const navigate = useNavigate();

  return (
    <section className="performance-state" role="status" aria-live="polite">
      <AlertCircle aria-hidden="true" />
      <h2>Không tải được số liệu hiệu suất</h2>
      <p>
        Kiểm tra kết nối rồi thử lại. Dữ liệu vận hành không thay đổi khi bạn
        tải lại trang này.
      </p>
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

/**
 * CSS-only trend chart (no charting library in package.json).
 * Each bucket is one vertical bar; height ∝ p95 latency. Error buckets get the
 * destructive color so a spike in failures is visible at a glance.
 */
const TrendChart = ({
  trend,
  window,
}: {
  trend: PerfTrendBucket[];
  window: PerfMetrics["window"];
}) => {
  const maxP95 = Math.max(1, ...trend.map((b) => b.p95_ms ?? 0));
  const totalErrors = trend.reduce((sum, b) => sum + b.errors, 0);
  const includesDate = window === "7d";
  const axisTicks = getTrendAxisTicks(trend, includesDate);

  return (
    <section className="performance-panel">
      <h2>Xu hướng độ trễ</h2>
      <p className="performance-panel-intro">
        Mỗi cột là 5 phút (p95). Cột đỏ có lượt lỗi. Tổng{" "}
        {totalErrors} lượt lỗi trong khoảng đã chọn.
      </p>
      {trend.length === 0 ? (
        <p className="performance-empty">Chưa có dữ liệu xu hướng.</p>
      ) : (
        <>
          <div
            className="performance-trend"
            role="img"
            aria-label="Xu hướng độ trễ p95 theo từng 5 phút"
          >
            {trend.map((b, i) => {
              const heightPct = Math.max(
                2,
                ((b.p95_ms ?? 0) / maxP95) * 100,
              );
              const hasError = b.errors > 0;
              const tooltip = `${formatTrendBucket(b.bucket, true)} · p95 ${fmtMs(b.p95_ms)} · ${b.turns} lượt · ${b.errors} lỗi`;
              return (
                <div
                  className={`performance-trend-bar${hasError ? " is-error" : ""}`}
                  key={`${b.bucket ?? i}`}
                  style={{ height: `${heightPct}%` }}
                  title={tooltip}
                />
              );
            })}
          </div>
          <div className="performance-trend-axis" aria-hidden="true">
            {axisTicks.map((tick) => {
              const position =
                trend.length > 1 ? (tick.index / (trend.length - 1)) * 100 : 0;
              const edgeClass =
                tick.index === 0
                  ? "is-first"
                  : tick.index === trend.length - 1
                    ? "is-last"
                    : "";

              return (
                <span
                  className={edgeClass}
                  key={tick.index}
                  style={{ left: `${position}%` }}
                >
                  {tick.label}
                </span>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
};

const TurnBadges = ({ turn }: { turn: PerfSlowTurn }) => (
  <div className="performance-badges">
    {turn.degraded ? (
      <span className="performance-badge is-destructive">Suy giảm</span>
    ) : null}
    {turn.retried_429 ? (
      <span className="performance-badge is-warning">Retry 429</span>
    ) : null}
  </div>
);

const TurnDetail = ({ turn }: { turn: PerfSlowTurn }) => (
  <div className="performance-row-detail">
    <div>
      <strong>Lượt gọi LLM (model ms)</strong>
      <ul>
        {turn.llm_call_ms?.length
          ? turn.llm_call_ms.map((ms, i) => (
              <li key={i}>
                Lần {i + 1}: <code>{ms} ms</code>
              </li>
            ))
          : null}
      </ul>
    </div>
    <div>
      <strong>Chi tiết tool</strong>
      <dl>
        {turn.tool_breakdown && Object.keys(turn.tool_breakdown).length > 0
          ? Object.entries(turn.tool_breakdown).map(([name, ms]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>{ms} ms</dd>
              </div>
            ))
          : null}
      </dl>
    </div>
    <div>
      <strong>DB & bypass</strong>
      <p>
        DB tổng: <code>{turn.db_ms ?? "—"} ms</code>
        {turn.faq_bypass_ms != null ? (
          <> · FAQ bypass: <code>{turn.faq_bypass_ms} ms</code></>
        ) : null}
      </p>
      {turn.db_breakdown && Object.keys(turn.db_breakdown).length > 0 ? (
        <dl>
          {Object.entries(turn.db_breakdown).map(([name, ms]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{ms} ms</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
    <div>
      <strong>Token & ngữ cảnh</strong>
      <p>
        Prompt: {turn.prompt_tokens ?? "—"} · Completion:{" "}
        {turn.completion_tokens ?? "—"} · Cached: {turn.cached_tokens ?? "—"}
      </p>
      <p>
        Model: <code>{turn.model_tier ?? "—"}</code> · Prompt cache:{" "}
        {turn.system_prompt_cache_hit == null
          ? "—"
          : turn.system_prompt_cache_hit
            ? "hit"
            : "miss"}
      </p>
      {turn.llm_backoff_ms ? (
        <p>
          Backoff 429: <code>{turn.llm_backoff_ms} ms</code>
        </p>
      ) : null}
      {turn.dark_time_ms != null && turn.total_ms != null ? (
        <p>
          Dark time: <code>{turn.dark_time_ms} ms</code> ·{" "}
          {turn.total_ms > 0
            ? `${Math.round((turn.dark_time_ms / turn.total_ms) * 100)}%`
            : "—"}{" "}
          (tổng trừ các giai đoạn đã đo)
        </p>
      ) : null}
    </div>
  </div>
);

const SlowestTurnsTable = ({ slow_turns }: { slow_turns: PerfSlowTurn[] }) => {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  return (
    <section className="performance-panel">
      <h2>Các lượt chậm nhất</h2>
      {slow_turns.length === 0 ? (
        <p className="performance-empty">
          Chưa có lượt nào được ghi nhận trong khoảng thời gian này.
        </p>
      ) : (
        <div
          className="performance-table-wrap"
          role="region"
          aria-label="Bảng các lượt chậm nhất"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th aria-label="Mở rộng" />
                <th>Thời gian</th>
                <th>Luồng</th>
                <th>Ý định</th>
                <th>LLM xử lý</th>
                <th>Chờ slot</th>
                <th>Lượt LLM</th>
                <th>Lượt tool</th>
                <th>Token</th>
                <th>Tổng</th>
                <th>Hàng đợi</th>
                <th>Cờ</th>
                <th>Kết quả</th>
              </tr>
            </thead>
            <tbody>
              {slow_turns.map((turn) => {
                const isOpen = expandedId === turn.id;
                const totalTokens =
                  (turn.prompt_tokens ?? 0) + (turn.completion_tokens ?? 0);
                return (
                  <Fragment key={turn.id}>
                    <tr>
                      <td>
                        <button
                          type="button"
                          className="performance-expand"
                          aria-expanded={isOpen}
                          aria-label={isOpen ? "Thu gọn" : "Mở rộng chi tiết"}
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
                      <td>
                        {turn.started_at
                          ? turn.started_at.replace("T", " ").slice(0, 19)
                          : "Chưa có"}
                      </td>
                      <td>
                        {LANE_LABELS[turn.lane ?? ""] ??
                          turn.lane ??
                          "Không rõ"}
                      </td>
                      <td>{turn.intent ?? "Chưa có"}</td>
                      <td>{fmtMs(turn.llm_model_ms)}</td>
                      <td>{fmtMs(turn.llm_queue_ms)}</td>
                      <td>{turn.llm_calls ?? "Chưa có"}</td>
                      <td>{turn.tool_calls ?? "Chưa có"}</td>
                      <td>{totalTokens > 0 ? totalTokens.toLocaleString() : "—"}</td>
                      <td>
                        <strong>{fmtMs(turn.total_ms)}</strong>
                      </td>
                      <td>{turn.queue_depth ?? "Chưa có"}</td>
                      <td>
                        <TurnBadges turn={turn} />
                      </td>
                      <td>
                        {OUTCOME_LABELS[turn.outcome] ??
                          turn.outcome ??
                          "Không rõ"}
                      </td>
                    </tr>
                    {isOpen ? (
                      <tr className="performance-detail-row">
                        <td colSpan={13}>
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
      )}
    </section>
  );
};

const PerformanceMetrics = ({ data }: { data: PerfMetrics }) => {
  const percentiles = data.percentiles ?? {};
  const hasLatencyData = STAGE_ORDER.some((key) => {
    const stage = percentiles[key];
    return stage?.p50 != null || stage?.p95 != null || stage?.p99 != null;
  });
  const maxP95 = Math.max(
    1,
    ...STAGE_ORDER.map((key) => percentiles[key]?.p95 ?? 0),
  );

  return (
    <>
      <section className="performance-metrics" aria-label="Tình trạng hệ thống">
        <Metric
          label="Hàng đợi"
          value={String(data.live.queue_depth)}
          hint="webhook đang chờ"
          tone="neutral"
        />
        <Metric
          label="Worker đang bận"
          value={`${data.live.busy_workers}/${data.live.total_workers}`}
          tone="success"
          hint="trên tổng worker"
        />
        <Metric
          label="LLM 429"
          value={String(data.live.minimax_429s_last_1m)}
          hint="trong 1 phút"
          tone={data.live.minimax_429s_last_1m > 0 ? "warning" : "success"}
        />
        <Metric
          label="Độ trễ LLM TB"
          value={fmtMs(data.live.llm_avg_latency_ms)}
          hint={`${data.live.llm_invokes_last_2m} lượt trong 2 phút`}
          tone="neutral"
        />
      </section>

      <TrendChart trend={data.trend ?? []} window={data.window} />

      <section className="performance-panel">
        <h2>Độ trễ theo giai đoạn</h2>
        <p className="performance-panel-intro">
          p50 · p95 · p99. “Tổng từ webhook” là độ trễ ứng viên thực sự chờ;
          thanh thể hiện p95.
        </p>
        {hasLatencyData ? STAGE_ORDER.map((key) => {
          const stage = percentiles[key] ?? { p50: null, p95: null, p99: null };
          const width = Math.max(2, ((stage.p95 ?? 0) / maxP95) * 100);
          const isLlmStage = key === "llm_queue" || key === "llm_model";

          return (
            <div className="performance-stage" key={key}>
              <div className="performance-stage-heading">
                <strong>{STAGE_LABELS[key]}</strong>
                <div className="performance-stage-values">
                  <span>p50 <b>{fmtMs(stage.p50)}</b></span>
                  <span className="is-benchmark">p95 <b>{fmtMs(stage.p95)}</b></span>
                  <span>p99 <b>{fmtMs(stage.p99)}</b></span>
                </div>
              </div>
              <div className="performance-bar" aria-hidden="true">
                <i
                  className={isLlmStage ? "is-llm" : ""}
                  style={{ width: `${width}%` }}
                />
              </div>
            </div>
          );
        }) : (
          <p className="performance-empty">
            Chưa có lượt xử lý nào để phân tích độ trễ.
          </p>
        )}
      </section>

      <section className="performance-counts">
        <CountCard
          title="Theo luồng"
          data={data.by_lane}
          labels={LANE_LABELS}
        />
        <CountCard
          title="Theo kết quả"
          data={data.by_outcome}
          labels={OUTCOME_LABELS}
        />
      </section>

      <ReliabilityPanel reliability={data.reliability} />

      <SlowestTurnsTable slow_turns={data.slow_turns} />
    </>
  );
};

const ReliabilityPanel = ({
  reliability,
}: {
  reliability: {
    send_unknown_count: number;
    suppressed_count: number;
    failed_count: number;
  };
}) => (
  <section className="performance-panel">
    <h2>Độ tin cậy giao gửi</h2>
    <div className="performance-reliability">
      <div className="reliability-stat">
        <span className="reliability-value">{reliability.send_unknown_count}</span>
        <span className="reliability-label">Gửi không xác định</span>
        <span className="reliability-hint">
          Timeout sau khi Zalo có thể đã nhận — không thử lại
        </span>
      </div>
      <div className="reliability-stat">
        <span className="reliability-value">{reliability.suppressed_count}</span>
        <span className="reliability-label">Bị chặn</span>
        <span className="reliability-hint">Recruiter tiếp quản giữa lượt</span>
      </div>
      <div className="reliability-stat">
        <span className="reliability-value">{reliability.failed_count}</span>
        <span className="reliability-label">Thất bại</span>
        <span className="reliability-hint">Lỗi gửi — sẽ thử lại</span>
      </div>
    </div>
  </section>
);

const CountCard = ({
  title,
  data,
  labels,
}: {
  title: string;
  data: Record<string, number>;
  labels: Record<string, string>;
}) => (
  <section className="performance-panel">
    <h2>{title}</h2>
    {Object.keys(data).length === 0 ? (
      <p className="performance-empty">
        Chưa có dữ liệu cho khoảng thời gian này.
      </p>
    ) : (
      <dl className="performance-count-list">
        {Object.entries(data).map(([key, value]) => (
          <div key={key}>
            <dt>{labels[key] ?? key}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    )}
  </section>
);

const PerformancePanel = () => {
  const [windowKey, setWindowKey] = useState<"1h" | "24h" | "7d">("24h");
  const { data, isPending, isError, refetch } = usePerformanceStats(windowKey);
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
              : "Theo dõi độ trễ và các lượt xử lý chậm trong khoảng thời gian đã chọn."}
          </p>
        </div>
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
