import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { AlertCircle, RefreshCw } from "lucide-react";
import { usePerformanceStats } from "./usePerformanceStats";
import "./performance.css";

const STAGE_LABELS: Record<string, string> = {
  webhook_to_pickup: "Webhook → nhận việc", preamble: "Khởi tạo", lead: "Lấy hồ sơ ứng viên",
  llm: "LLM / RAG", safety: "Kiểm duyệt an toàn", send: "Gửi Zalo", total: "Tổng cộng",
};
const LANE_LABELS: Record<string, string> = { agent: "Agent (LLM)", fast_lane: "Fast lane", faq_bypass: "FAQ bypass", unknown: "Không rõ" };
const STAGE_ORDER = ["webhook_to_pickup", "preamble", "lead", "llm", "safety", "send", "total"];
const WINDOWS = [{ key: "1h", label: "1 giờ" }, { key: "24h", label: "24 giờ" }, { key: "7d", label: "7 ngày" }] as const;
const fmtMs = (value: number | null | undefined) => value == null ? "Chưa có" : value >= 1000 ? `${(value / 1000).toFixed(1)} giây` : `${value} ms`;

const Metric = ({ label, value, hint }: { label: string; value: string; hint?: string }) => <article className="performance-metric"><p>{label}</p><strong>{value}</strong>{hint ? <small>{hint}</small> : null}</article>;

const PerformancePanel = () => {
  const [windowKey, setWindowKey] = useState<"1h" | "24h" | "7d">("24h");
  const { data, isPending, isError, refetch } = usePerformanceStats(windowKey);
  const navigate = useNavigate();

  if (isPending) return <div className="performance-page" aria-busy="true"><header><p className="performance-kicker">Vận hành</p><h1>Hiệu suất chatbot</h1><p>Đang tải số liệu cho khoảng thời gian đã chọn.</p></header><div className="performance-skeletons">{Array.from({ length: 4 }, (_, index) => <span key={index} />)}</div></div>;
  if (isError || !data) return <div className="performance-page"><header><p className="performance-kicker">Vận hành</p><h1>Hiệu suất chatbot</h1></header><section className="performance-state" role="status" aria-live="polite"><AlertCircle aria-hidden="true" /><h2>Không tải được số liệu hiệu suất</h2><p>Kiểm tra kết nối rồi thử lại. Dữ liệu vận hành không thay đổi khi bạn tải lại trang này.</p><div><Button onClick={() => void refetch()}><RefreshCw className="size-4" />Thử lại</Button><Button variant="outline" onClick={() => navigate("/")}>Về Tổng quan</Button></div></section></div>;

  const percentiles = data.percentiles ?? {};
  const maxP95 = Math.max(1, ...STAGE_ORDER.map((key) => percentiles[key]?.p95 ?? 0));
  return <div className="performance-page">
    <header className="performance-header"><div><p className="performance-kicker">Vận hành</p><h1>Hiệu suất chatbot</h1><p>Theo dõi độ trễ và các lượt xử lý chậm theo thời gian thực.</p></div><div className="performance-window" aria-label="Khoảng thời gian">{WINDOWS.map((window) => <button key={window.key} type="button" aria-pressed={windowKey === window.key} onClick={() => setWindowKey(window.key)}>{window.label}</button>)}</div></header>
    <section className="performance-metrics" aria-label="Tình trạng hệ thống"><Metric label="Hàng đợi" value={String(data.live.queue_depth)} hint="webhook đang chờ" /><Metric label="Worker đang chạy" value={`${data.live.busy_workers}/${data.live.total_workers}`} /><Metric label="LLM 429" value={String(data.live.minimax_429s_last_1m)} hint="trong 1 phút" /><Metric label="Fallback" value={String(data.live.llm_fallbacks_last_2m)} hint={`Độ trễ TB: ${fmtMs(data.live.llm_avg_latency_ms)}`} /></section>
    <section className="performance-panel"><h2>Độ trễ theo giai đoạn</h2><p className="performance-panel-intro">p50 · p95 · p99. Thanh thể hiện p95; LLM thường là điểm nghẽn cần theo dõi.</p>{STAGE_ORDER.map((key) => { const stage = percentiles[key] ?? { p50: null, p95: null, p99: null }; const width = Math.max(2, ((stage.p95 ?? 0) / maxP95) * 100); return <div className="performance-stage" key={key}><div><strong>{STAGE_LABELS[key]}</strong><span>{fmtMs(stage.p50)} · <b>{fmtMs(stage.p95)}</b> · {fmtMs(stage.p99)}</span></div><div className="performance-bar" aria-hidden="true"><i className={key === "llm" ? "is-llm" : ""} style={{ width: `${width}%` }} /></div></div>; })}</section>
    <section className="performance-counts"><CountCard title="Theo luồng" data={data.by_lane} labels={LANE_LABELS} /><CountCard title="Theo kết quả" data={data.by_outcome} labels={{}} /></section>
    <section className="performance-panel"><h2>Các lượt chậm nhất</h2>{data.slow_turns.length === 0 ? <p className="performance-empty">Chưa có lượt nào được ghi nhận trong khoảng thời gian này.</p> : <div className="performance-table-wrap" role="region" aria-label="Bảng các lượt chậm nhất" tabIndex={0}><table><thead><tr><th>Thời gian</th><th>Luồng</th><th>LLM</th><th>Tổng</th><th>Hàng đợi</th><th>Kết quả</th></tr></thead><tbody>{data.slow_turns.map((turn) => <tr key={turn.id}><td>{turn.started_at ? turn.started_at.replace("T", " ").slice(0, 19) : "Chưa có"}</td><td>{LANE_LABELS[turn.lane ?? ""] ?? turn.lane ?? "Không rõ"}</td><td>{fmtMs(turn.llm_ms)}</td><td><strong>{fmtMs(turn.total_ms)}</strong></td><td>{turn.queue_depth ?? "Chưa có"}</td><td>{turn.outcome || "Không rõ"}</td></tr>)}</tbody></table></div>}</section>
  </div>;
};

const CountCard = ({ title, data, labels }: { title: string; data: Record<string, number>; labels: Record<string, string> }) => <section className="performance-panel"><h2>{title}</h2>{Object.keys(data).length === 0 ? <p className="performance-empty">Chưa có dữ liệu cho khoảng thời gian này.</p> : <dl className="performance-count-list">{Object.entries(data).map(([key, value]) => <div key={key}><dt>{labels[key] ?? key}</dt><dd>{value}</dd></div>)}</dl>}</section>;

export const PerformancePage = () => <PerformancePanel />;
