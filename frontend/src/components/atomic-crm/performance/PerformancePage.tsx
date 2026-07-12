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
  llm_call_per: "LLM — mỗi lượt gọi",
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
  "llm_call_per",
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
const CANDIDATE_STAGES = new Set(["webhook_to_pickup", "total", "end_to_end"]);
const STAGE_TARGETS: Record<string, number> = {
  webhook_to_pickup: 200,
  preamble: 5000,
  lead: 2000,
  system_prompt: 2000,
  llm_queue: 5000,
  llm_model: 10000,
  llm_call_per: 10000,
  db: 2000,
  send: 1000,
  total: 10000,
  end_to_end: 10000,
};

type Tone = "neutral" | "success" | "warning" | "danger";
type Icon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

const fmtMs = (value: number | null | undefined): string =>
  value == null
    ? "Chưa có"
    : value >= 1000
      ? `${(value / 1000).toFixed(1)} giây`
      : `${value} ms`;

const fmtShortMs = (value: number | null | undefined): string =>
  value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;

const formatStartedAt = (value: string | null): string =>
  value ? value.replace("T", " ").slice(0, 19) : "Chưa có";

const getStageTone = (key: string, p95: number | null | undefined): Tone => {
  const target = STAGE_TARGETS[key];
  if (p95 == null || target == null) return "neutral";
  if (p95 > target * 1.5) return "danger";
  if (p95 > target) return "warning";
  return "success";
};

const getSlowTurnTone = (turn: PerfSlowTurn): Tone => {
  if (turn.outcome === "ERROR" || turn.degraded || (turn.total_ms ?? 0) > 20_000) {
    return "danger";
  }
  if (turn.retried_429 || (turn.total_ms ?? 0) > 10_000) return "warning";
  return "neutral";
};

const likelyBottleneck = (turn: PerfSlowTurn): string => {
  const stages = [
    ["LLM xử lý", turn.llm_model_ms],
    ["LLM chờ slot", turn.llm_queue_ms],
    ["Cơ sở dữ liệu", turn.db_ms],
    ["Gửi Zalo", turn.faq_bypass_ms],
  ] as const;
  const candidate = stages.reduce<(typeof stages)[number]>(
    (largest, stage) => (stage[1] ?? 0) > (largest[1] ?? 0) ? stage : largest,
    stages[0],
  );
  return candidate[1] == null ? "Chưa xác định" : `${candidate[0]} (${fmtShortMs(candidate[1])})`;
};

const Status = ({ tone, children }: { tone: Tone; children: string }) => {
  const StatusIcon = tone === "danger" ? AlertCircle : tone === "warning" ? TriangleAlert : tone === "success" ? CheckCircle2 : Activity;
  return (
    <span className={`performance-status is-${tone}`}>
      <StatusIcon aria-hidden="true" />
      {children}
    </span>
  );
};

const Metric = ({ label, value, hint, tone, icon: Icon }: { label: string; value: string; hint: string; tone: Tone; icon: Icon }) => (
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
  <div className="performance-skeletons" aria-label="Đang tải số liệu hiệu suất">
    {Array.from({ length: 8 }, (_, index) => <span key={index} className={index > 4 ? "is-panel" : undefined} />)}
  </div>
);

const PerformanceError = ({ onRetry }: { onRetry: () => void }) => {
  const navigate = useNavigate();
  return (
    <section className="performance-state" role="status" aria-live="polite">
      <AlertCircle aria-hidden="true" />
      <h2>Không tải được số liệu hiệu suất</h2>
      <p>Kiểm tra kết nối rồi thử lại. Dữ liệu vận hành không thay đổi khi bạn tải lại trang này.</p>
      <div>
        <Button onClick={onRetry}><RefreshCw className="size-4" />Thử lại</Button>
        <Button variant="outline" onClick={() => navigate("/")}>Về Tổng quan</Button>
      </div>
    </section>
  );
};

const TrendChart = ({ trend, window }: { trend: PerfTrendBucket[]; window: PerfMetrics["window"] }) => {
  const maxP95 = Math.max(10_000, ...trend.map((bucket) => bucket.p95_ms ?? 0));
  const totalErrors = trend.reduce((sum, bucket) => sum + bucket.errors, 0);
  const axisTicks = getTrendAxisTicks(trend, window === "7d");
  return (
    <section className="performance-panel performance-trend-panel">
      <div className="performance-section-heading">
        <div><h2>Xu hướng độ trễ ứng viên chờ</h2><p>p95 theo từng 5 phút. Mục tiêu candidate-visible: ≤ 10 giây.</p></div>
        <div className="performance-legend" aria-label="Chú giải biểu đồ"><span><i className="is-line" />p95</span><span><i className="is-target" />Mục tiêu 10 giây</span></div>
      </div>
      {trend.length === 0 ? <p className="performance-empty">Chưa có dữ liệu xu hướng.</p> : <>
        <div className="performance-trend" role="img" aria-label={`Xu hướng độ trễ p95; ${totalErrors} lượt lỗi trong khoảng đã chọn`}>
          <span className="performance-target-line" style={{ bottom: `${Math.min(96, (10_000 / maxP95) * 100)}%` }}><b>10 giây</b></span>
          {trend.map((bucket, index) => {
            const height = Math.max(2, ((bucket.p95_ms ?? 0) / maxP95) * 100);
            const tooltip = `${formatTrendBucket(bucket.bucket, true)} · p95 ${fmtMs(bucket.p95_ms)} · ${bucket.turns} lượt · ${bucket.errors} lỗi`;
            return <button className={`performance-trend-bar${bucket.errors > 0 ? " is-error" : ""}`} key={`${bucket.bucket ?? index}`} style={{ height: `${height}%` }} title={tooltip} aria-label={tooltip} type="button" />;
          })}
        </div>
        <div className="performance-trend-axis" aria-hidden="true">{axisTicks.map((tick) => <span key={tick.index} style={{ left: `${trend.length > 1 ? (tick.index / (trend.length - 1)) * 100 : 0}%` }} className={tick.index === 0 ? "is-first" : tick.index === trend.length - 1 ? "is-last" : ""}>{tick.label}</span>)}</div>
        <p className="performance-chart-note"><TriangleAlert aria-hidden="true" /> {totalErrors > 0 ? `${totalErrors} lượt lỗi cần đối chiếu với các phiên vượt ngưỡng.` : "Không ghi nhận lượt lỗi trong khoảng đã chọn."}</p>
      </>}
    </section>
  );
};

type Signal = { id: string; tone: Tone; title: string; detail: string; value: string; icon: Icon };

const AttentionQueue = ({ data }: { data: PerfMetrics }) => {
  const endToEnd = data.percentiles.end_to_end?.p95;
  const delivery = data.reliability;
  const signals: Signal[] = [];
  if (endToEnd != null && endToEnd > STAGE_TARGETS.end_to_end) signals.push({ id: "latency", tone: getStageTone("end_to_end", endToEnd), title: "Độ trễ p95 vượt mục tiêu", detail: "Ứng viên có thể phải chờ phản hồi lâu hơn kỳ vọng.", value: fmtMs(endToEnd), icon: Clock3 });
  if (data.live.minimax_429s_last_1m > 0) signals.push({ id: "rate-limit", tone: "warning", title: "LLM có phản hồi 429", detail: "Đã có retry hoặc nguy cơ làm chậm các lượt mới.", value: `${data.live.minimax_429s_last_1m} trong 1 phút`, icon: Cpu });
  if ((delivery?.failed_count ?? 0) > 0) signals.push({ id: "failed", tone: "danger", title: "Có lượt gửi thất bại", detail: "Kiểm tra các lượt chậm để xác nhận việc giao tin nhắn.", value: String(delivery?.failed_count), icon: Send });
  if ((delivery?.send_unknown_count ?? 0) > 0) signals.push({ id: "unknown", tone: "warning", title: "Có lượt gửi không xác định", detail: "Zalo có thể đã nhận tin; không tự động gửi lại để tránh trùng.", value: String(delivery?.send_unknown_count), icon: ShieldAlert });
  if (data.live.total_workers > 0 && data.live.busy_workers >= data.live.total_workers) signals.push({ id: "capacity", tone: "warning", title: "Worker đang dùng hết công suất", detail: "Theo dõi hàng đợi để phát hiện áp lực xử lý tăng.", value: `${data.live.busy_workers}/${data.live.total_workers}`, icon: Server });
  if (signals.length === 0) signals.push({ id: "stable", tone: "success", title: "Chưa có tín hiệu cần xử lý", detail: "Dữ liệu hiện tại không cho thấy áp lực giao gửi hay xử lý bất thường.", value: "Ổn định", icon: CheckCircle2 });
  return (
    <section className="performance-panel performance-attention-panel">
      <div className="performance-section-heading"><div><h2>Tín hiệu cần xử lý <span>{signals.filter((signal) => signal.tone !== "success").length}</span></h2><p>Ưu tiên theo mức độ ảnh hưởng tới ứng viên và giao gửi.</p></div></div>
      <ul className="performance-signal-list">{signals.slice(0, 5).map((signal) => { const SignalIcon = signal.icon; return <li key={signal.id} className={`is-${signal.tone}`}><SignalIcon aria-hidden={true} /><div><strong>{signal.title}</strong><small>{signal.detail}</small></div><b>{signal.value}</b><a href="#slow-turns" aria-label={`Xem lượt liên quan đến ${signal.title}`}><ArrowRight aria-hidden="true" /></a></li>; })}</ul>
    </section>
  );
};

const StageMatrix = ({ data }: { data: PerfMetrics }) => {
  const percentiles = data.percentiles ?? {};
  const rows = STAGE_ORDER.filter((key) => percentiles[key]?.p50 != null || percentiles[key]?.p95 != null || percentiles[key]?.p99 != null);
  const renderRow = (key: string) => {
    const stage = percentiles[key];
    const tone = getStageTone(key, stage?.p95);
    const target = STAGE_TARGETS[key];
    const callsP95 = percentiles.llm_calls_per?.p95;
    return <tr key={key}><td><strong>{STAGE_LABELS[key]}</strong>{key === "llm_model" && callsP95 != null ? <small>~{callsP95} lượt/turn — cộng dồn</small> : key === "end_to_end" ? <small>Độ trễ ứng viên thực sự chờ</small> : null}</td><td>{fmtMs(stage?.p50)}</td><td><b>{fmtMs(stage?.p95)}</b></td><td>{fmtMs(stage?.p99)}</td><td>{target == null ? "—" : `≤ ${fmtMs(target)}`}</td><td><Status tone={tone}>{tone === "danger" ? "Vượt ngưỡng" : tone === "warning" ? "Cần cải thiện" : tone === "success" ? "Đạt" : "Chưa có mục tiêu"}</Status></td></tr>;
  };
  const candidate = rows.filter((key) => CANDIDATE_STAGES.has(key));
  const internal = rows.filter((key) => !CANDIDATE_STAGES.has(key));
  return <section className="performance-panel performance-matrix"><div className="performance-section-heading"><div><h2>Chẩn đoán độ trễ</h2><p>p50 · p95 · p99; các điểm đo nội bộ là chi tiết chẩn đoán, không cộng dồn.</p></div></div>{rows.length === 0 ? <p className="performance-empty">Chưa có lượt xử lý nào để phân tích độ trễ.</p> : <div className="performance-table-wrap" role="region" aria-label="Bảng chẩn đoán độ trễ" tabIndex={0}><table><thead><tr><th>Giai đoạn</th><th>p50</th><th>p95</th><th>p99</th><th>Mục tiêu</th><th>Trạng thái</th></tr></thead><tbody>{candidate.length > 0 ? <tr className="performance-group-row"><th colSpan={6}>Chờ ứng viên</th></tr> : null}{candidate.map(renderRow)}{internal.length > 0 ? <tr className="performance-group-row"><th colSpan={6}>Chẩn đoán nội bộ</th></tr> : null}{internal.map(renderRow)}</tbody></table></div>}</section>;
};

const TurnDetail = ({ turn }: { turn: PerfSlowTurn }) => <div className="performance-row-detail"><div><strong>Điều phối</strong><p>Hàng đợi: <code>{turn.queue_depth ?? "—"}</code> · Chờ slot: <code>{fmtMs(turn.llm_queue_ms)}</code></p><p>Độ trễ chưa phân bổ: <code>{fmtMs(turn.dark_time_ms)}</code></p></div><div><strong>LLM & tool</strong><p>{turn.llm_calls ?? "—"} lượt LLM · {turn.tool_calls ?? "—"} lượt tool</p><p>Model: <code>{turn.model_tier ?? "—"}</code>{turn.retried_429 ? " · Đã retry 429" : ""}</p></div><div><strong>Dữ liệu & token</strong><p>DB: <code>{fmtMs(turn.db_ms)}</code> · Tool: <code>{fmtMs(turn.tool_ms)}</code></p><p>Prompt: {turn.prompt_tokens ?? "—"} · Completion: {turn.completion_tokens ?? "—"}</p></div><div><strong>Trace</strong><p><code>{turn.conversation_id}</code></p><p>Intent: {turn.intent ?? "Chưa có"}</p></div></div>;

const SlowestTurns = ({ slowTurns }: { slowTurns: PerfSlowTurn[] }) => {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  return <section className="performance-panel performance-slow-turns" id="slow-turns"><div className="performance-section-heading"><div><h2>Lượt cần xem <span>{slowTurns.length}</span></h2><p>Ưu tiên những lượt ảnh hưởng tới phản hồi hoặc giao gửi.</p></div></div>{slowTurns.length === 0 ? <p className="performance-empty">Chưa có lượt nào được ghi nhận trong khoảng thời gian này.</p> : <><div className="performance-table-wrap" role="region" aria-label="Bảng lượt cần xem" tabIndex={0}><table><thead><tr><th>Mức độ</th><th>Thời gian</th><th>Tổng</th><th>Nút thắt nhiều khả năng</th><th>Luồng</th><th>Kết quả giao gửi</th><th aria-label="Mở rộng" /></tr></thead><tbody>{slowTurns.map((turn) => { const tone = getSlowTurnTone(turn); const isOpen = expandedId === turn.id; return <Fragment key={turn.id}><tr className={isOpen ? "is-open" : undefined}><td><Status tone={tone}>{tone === "danger" ? "Cao" : tone === "warning" ? "Trung bình" : "Thấp"}</Status></td><td>{formatStartedAt(turn.started_at)}</td><td><b>{fmtMs(turn.total_ms)}</b></td><td>{likelyBottleneck(turn)}</td><td>{LANE_LABELS[turn.lane ?? ""] ?? turn.lane ?? "Không rõ"}</td><td><Status tone={turn.outcome === "ERROR" ? "danger" : "success"}>{OUTCOME_LABELS[turn.outcome] ?? turn.outcome ?? "Không rõ"}</Status></td><td><button type="button" className="performance-expand" aria-expanded={isOpen} aria-label={isOpen ? "Thu gọn chi tiết" : "Mở rộng chi tiết"} onClick={() => setExpandedId(isOpen ? null : turn.id)}>{isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</button></td></tr>{isOpen ? <tr className="performance-detail-row"><td colSpan={7}><TurnDetail turn={turn} /></td></tr> : null}</Fragment>; })}</tbody></table></div><div className="performance-turn-cards">{slowTurns.map((turn) => { const tone = getSlowTurnTone(turn); return <article key={turn.id} className={`is-${tone}`}><div><Status tone={tone}>{tone === "danger" ? "Cao" : tone === "warning" ? "Trung bình" : "Thấp"}</Status><time>{formatStartedAt(turn.started_at)}</time></div><strong>{fmtMs(turn.total_ms)}</strong><p>{likelyBottleneck(turn)}</p><button type="button" aria-expanded={expandedId === turn.id} onClick={() => setExpandedId(expandedId === turn.id ? null : turn.id)}>{expandedId === turn.id ? "Thu gọn chi tiết" : "Xem chi tiết"}<ChevronRight aria-hidden="true" /></button>{expandedId === turn.id ? <TurnDetail turn={turn} /> : null}</article>; })}</div></> }</section>;
};

const SupportingStats = ({ data }: { data: PerfMetrics }) => {
  const total = Object.values(data.by_outcome).reduce((sum, value) => sum + value, 0);
  const sent = data.by_outcome.SENT ?? 0;
  const sendRate = total > 0 ? `${Math.round((sent / total) * 100)}%` : "—";
  const lanes = Object.entries(data.by_lane).sort(([, a], [, b]) => b - a);
  return <section className="performance-supporting" aria-label="Chỉ số hỗ trợ"><article><div><Send aria-hidden="true" /><h2>Độ tin cậy giao gửi</h2></div><strong>{sendRate}</strong><p>{sent.toLocaleString()} đã gửi · {data.reliability?.failed_count ?? 0} thất bại · {data.reliability?.send_unknown_count ?? 0} không xác định</p></article><article><div><Activity aria-hidden="true" /><h2>Phân bố theo lane</h2></div>{lanes.length === 0 ? <p>Chưa có dữ liệu.</p> : <ul>{lanes.slice(0, 3).map(([lane, value]) => <li key={lane}><span>{LANE_LABELS[lane] ?? lane}</span><b>{value.toLocaleString()}</b></li>)}</ul>}</article><article><div><Database aria-hidden="true" /><h2>Độ đầy đủ dữ liệu</h2></div><strong>{data.trend.length > 0 ? "Có dữ liệu" : "Chưa đủ"}</strong><p>{data.trend.length > 0 ? `${data.trend.length} điểm xu hướng trong khoảng đã chọn.` : "Chưa có bucket thời gian để kiểm tra."}</p></article></section>;
};

const PerformanceMetrics = ({ data }: { data: PerfMetrics }) => {
  const endToEnd = data.percentiles.end_to_end?.p95;
  const workerTone: Tone = data.live.total_workers > 0 && data.live.busy_workers >= data.live.total_workers ? "warning" : "success";
  const deliveryTone: Tone = (data.reliability?.failed_count ?? 0) > 0 ? "danger" : (data.reliability?.send_unknown_count ?? 0) > 0 ? "warning" : "success";
  return <>
    <section className="performance-metrics" aria-label="Tình trạng hệ thống">
      <Metric label="Hàng đợi" value={String(data.live.queue_depth)} hint="webhook đang chờ" tone={data.live.queue_depth > 0 ? "warning" : "neutral"} icon={Server} />
      <Metric label="Sức chứa worker" value={`${data.live.busy_workers}/${data.live.total_workers}`} hint="worker đang bận" tone={workerTone} icon={Cpu} />
      <Metric label="Độ trễ p95" value={fmtMs(endToEnd)} hint="tổng từ webhook · mục tiêu ≤ 10 giây" tone={getStageTone("end_to_end", endToEnd)} icon={Clock3} />
      <Metric label="LLM 429" value={String(data.live.minimax_429s_last_1m)} hint="trong 1 phút gần nhất" tone={data.live.minimax_429s_last_1m > 0 ? "warning" : "success"} icon={ShieldAlert} />
      <Metric label="Giao gửi rủi ro" value={String((data.reliability?.failed_count ?? 0) + (data.reliability?.send_unknown_count ?? 0))} hint="thất bại + không xác định" tone={deliveryTone} icon={Send} />
      <Metric label="Lượt xử lý" value={Object.values(data.by_outcome).reduce((sum, value) => sum + value, 0).toLocaleString()} hint={`trong ${data.window === "1h" ? "1 giờ" : data.window === "7d" ? "7 ngày" : "24 giờ"}`} tone="neutral" icon={Activity} />
    </section>
    <section className="performance-primary-grid"><TrendChart trend={data.trend ?? []} window={data.window} /><AttentionQueue data={data} /></section>
    <StageMatrix data={data} />
    <SlowestTurns slowTurns={data.slow_turns} />
    <SupportingStats data={data} />
  </>;
};

const PerformancePanel = () => {
  const [windowKey, setWindowKey] = useState<"1h" | "24h" | "7d">("24h");
  const { data, isPending, isError, refetch, dataUpdatedAt } = usePerformanceStats(windowKey);
  const freshness = useMemo(() => dataUpdatedAt ? new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(dataUpdatedAt) : null, [dataUpdatedAt]);
  const hasError = isError || !data;
  return <div className="performance-page" aria-busy={isPending || undefined}>
    <header className="performance-header"><div><p className="performance-kicker">Vận hành</p><h1>Hiệu suất chatbot</h1><p>{isPending ? "Đang tải số liệu cho khoảng thời gian đã chọn." : "Theo dõi trải nghiệm ứng viên, năng lực xử lý và độ tin cậy giao gửi."}</p></div><div className="performance-header-actions"><div className="performance-window" aria-label="Khoảng thời gian">{WINDOWS.map((window) => <button key={window.key} type="button" aria-pressed={windowKey === window.key} onClick={() => setWindowKey(window.key)}>{window.label}</button>)}</div><button type="button" className="performance-refresh" onClick={() => void refetch()} disabled={isPending}><RefreshCw className={isPending ? "is-spinning" : undefined} aria-hidden="true" />{freshness ? `Cập nhật lúc ${freshness}` : "Cập nhật dữ liệu"}</button></div></header>
    {isPending ? <PerformanceLoading /> : null}
    {!isPending && hasError ? <PerformanceError onRetry={() => void refetch()} /> : null}
    {!isPending && !hasError && data ? <PerformanceMetrics data={data} /> : null}
  </div>;
};

export const PerformancePage = () => <PerformancePanel />;
