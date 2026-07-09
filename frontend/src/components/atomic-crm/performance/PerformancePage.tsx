import { useState } from "react";

import { InboxIcons } from "../conversations/InboxIcons";
import { WorkspaceIconRail } from "../conversations/WorkspaceShell";
import "../conversations/inbox.css";
import { usePerformanceStats } from "./usePerformanceStats";

// "Hiệu suất" — per-stage turn-latency dashboard. Renders live queue tiles,
// per-stage p50/p95/p99 CSS bars (the LLM stage is highlighted, since it is
// the usual bottleneck), lane/outcome counts, and the slowest recent turns.
// Vietnamese-only; colors use CSS variables so light/dark both render.

const STAGE_LABELS: Record<string, string> = {
  webhook_to_pickup: "Webhook → nhận việc",
  preamble: "Khởi tạo (build_deps)",
  lead: "Lấy profile ứng viên",
  llm: "LLM / RAG",
  safety: "Kiểm duyệt an toàn",
  send: "Gửi Zalo",
  total: "Tổng cộng",
};

const LANE_LABELS: Record<string, string> = {
  agent: "Agent (LLM)",
  fast_lane: "Fast lane",
  faq_bypass: "FAQ bypass",
  unknown: "Không rõ",
};

const STAGE_ORDER = [
  "webhook_to_pickup",
  "preamble",
  "lead",
  "llm",
  "safety",
  "send",
  "total",
];

const WINDOWS = [
  { key: "1h", label: "1 giờ" },
  { key: "24h", label: "24 giờ" },
  { key: "7d", label: "7 ngày" },
] as const;

const fmtMs = (v: number | null | undefined): string =>
  v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`;

const Tile = ({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) => (
  <div className="rounded-md border bg-card p-3">
    <div className="text-xs text-muted-foreground">{label}</div>
    <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
    {hint ? <div className="text-[11px] text-muted-foreground">{hint}</div> : null}
  </div>
);

const PerformancePanel = () => {
  const [windowKey, setWindowKey] = useState<"1h" | "24h" | "7d">("24h");
  const { data, isPending, isError } = usePerformanceStats(windowKey);

  if (isPending) {
    return <div className="p-4 text-muted-foreground">Đang tải số liệu hiệu suất…</div>;
  }
  if (isError || !data) {
    return <div className="p-4 text-muted-foreground">Không tải được số liệu hiệu suất.</div>;
  }

  const live = data.live;
  const pct = data.percentiles ?? {};
  const maxP95 = Math.max(1, ...STAGE_ORDER.map((k) => pct[k]?.p95 ?? 0));

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Hiệu suất Chatbot</h1>
        <div className="flex gap-1">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              onClick={() => setWindowKey(w.key)}
              className={`rounded-md border px-2 py-1 text-xs ${
                windowKey === w.key
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile label="Hàng đợi" value={`${live.queue_depth}`} hint="webhook_high" />
        <Tile
          label="Worker đang chạy"
          value={`${live.busy_workers}/${live.total_workers}`}
        />
        <Tile label="LLM 429 (1 phút)" value={`${live.minimax_429s_last_1m}`} />
        <Tile
          label="Fallback (2 phút)"
          value={`${live.llm_fallbacks_last_2m}`}
          hint={`Độ trễ TB: ${fmtMs(live.llm_avg_latency_ms)}`}
        />
      </div>

      <div className="rounded-md border p-3">
        <div className="mb-2 text-sm font-medium">
          Độ trễ theo giai đoạn (p50 · p95 · p99)
        </div>
        <div className="flex flex-col gap-2">
          {STAGE_ORDER.map((key) => {
            const s = pct[key] ?? { p50: null, p95: null, p99: null };
            const w = Math.max(2, ((s.p95 ?? 0) / maxP95) * 100);
            const isLlm = key === "llm";
            return (
              <div key={key} className="flex flex-col gap-1">
                <div className="flex items-center justify-between text-xs">
                  <span className={isLlm ? "font-semibold" : ""}>
                    {STAGE_LABELS[key]}
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    {fmtMs(s.p50)} ·{" "}
                    <span className="font-medium text-foreground">
                      {fmtMs(s.p95)}
                    </span>{" "}
                    · {fmtMs(s.p99)}
                  </span>
                </div>
                <div className="h-2 w-full rounded bg-muted">
                  <div
                    className="h-2 rounded"
                    style={{
                      width: `${w}%`,
                      background: isLlm ? "var(--primary)" : "var(--chart-1)",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-2 text-[11px] text-muted-foreground">
          Thanh dài = p95. Mục tiêu ~10s/lượt. Ô màu nhấn là giai đoạn LLM — thường là điểm nghẽn.
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <CountCard title="Theo luồng" data={data.by_lane} labels={LANE_LABELS} />
        <CountCard title="Theo kết quả" data={data.by_outcome} labels={{}} />
      </div>

      <div className="rounded-md border">
        <div className="border-b p-3 text-sm font-medium">Các lượt chậm nhất</div>
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="p-2 text-left font-medium">Thời gian</th>
              <th className="p-2 text-left font-medium">Luồng</th>
              <th className="p-2 text-right font-medium">LLM</th>
              <th className="p-2 text-right font-medium">Tổng</th>
              <th className="p-2 text-right font-medium">Hàng đợi</th>
              <th className="p-2 text-left font-medium">Kết quả</th>
            </tr>
          </thead>
          <tbody>
            {data.slow_turns.length === 0 ? (
              <tr>
                <td colSpan={6} className="p-3 text-muted-foreground">
                  Chưa có lượt nào được ghi nhận trong khoảng này.
                </td>
              </tr>
            ) : (
              data.slow_turns.map((t) => (
                <tr key={t.id} className="border-t">
                  <td className="p-2">
                    {t.started_at ? t.started_at.replace("T", " ").slice(0, 19) : "—"}
                  </td>
                  <td className="p-2">{LANE_LABELS[t.lane ?? ""] ?? t.lane ?? "—"}</td>
                  <td className="p-2 text-right tabular-nums">{fmtMs(t.llm_ms)}</td>
                  <td className="p-2 text-right font-medium tabular-nums">
                    {fmtMs(t.total_ms)}
                  </td>
                  <td className="p-2 text-right tabular-nums">{t.queue_depth ?? "—"}</td>
                  <td className="p-2">{t.outcome}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const CountCard = ({
  title,
  data,
  labels,
}: {
  title: string;
  data: Record<string, number>;
  labels: Record<string, string>;
}) => (
  <div className="rounded-md border p-3">
    <div className="mb-1 font-medium">{title}</div>
    {Object.keys(data).length === 0 ? (
      <div className="text-muted-foreground">Chưa có dữ liệu</div>
    ) : (
      Object.entries(data).map(([k, v]) => (
        <div key={k} className="flex justify-between">
          <span>{labels[k] ?? k}</span>
          <span className="tabular-nums">{v}</span>
        </div>
      ))
    )}
  </div>
);

export const PerformancePage = () => (
  <div className="inbox-bg-container dashboard-workspace">
    <InboxIcons />
    <main className="app dashboard-app" id="app">
      <WorkspaceIconRail />
      <section className="panel center-panel dashboard-center-panel">
        <div className="dashboard-workspace-content">
          <PerformancePanel />
        </div>
      </section>
    </main>
  </div>
);
