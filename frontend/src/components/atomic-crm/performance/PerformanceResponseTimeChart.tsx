import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Inbox } from "lucide-react";

import { EmptyState } from "../kit";
import {
  formatSecondsValue,
  toTrendRows,
  trendTooltipFormatter,
} from "./performanceFormat";
import type { PerfTrendBucket, PerfWindow } from "./usePerformanceStats";

const TARGET_SECONDS = 10;

/**
 * End-to-end response time over the selected window: p95 against the ≤10s
 * target, with the same series mirrored into a clipped table so the data is not
 * chart-only (recharts owns the plot, the table is the accessible pair).
 */
export const PerformanceResponseTimeChart = ({
  trend,
  window,
}: {
  trend: PerfTrendBucket[];
  window: PerfWindow;
}) => {
  if (trend.length === 0) {
    // CHAT-20: a chart with no data says so through the console's shared
    // empty-state pattern (icon + message) instead of a bare surface.
    return (
      <EmptyState
        icon={<Inbox className="size-6" aria-hidden="true" />}
        title="Chưa có dữ liệu xu hướng"
        description="Chưa có dữ liệu trong khoảng thời gian này."
      />
    );
  }

  const rows = toTrendRows(trend, window);

  return (
    <>
      <div className="performance-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={rows}
            margin={{ top: 8, right: 12, bottom: 0, left: 0 }}
          >
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              minTickGap={24}
              tick={{ fontSize: 11 }}
            />
            <YAxis
              width={44}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => `${value}s`}
              tick={{ fontSize: 11 }}
            />
            <Tooltip formatter={trendTooltipFormatter} />
            <ReferenceLine
              y={TARGET_SECONDS}
              stroke="var(--muted-foreground)"
              strokeDasharray="4 4"
              label={{
                value: "10 giây",
                // CHAT-20: the label used to sit on the dashed threshold and
                // the p95 series at once. Offset it above the line's end
                // (insideTopRight anchors to the line's bbox) and give it a
                // panel-coloured halo so a crossing spike stays readable
                // under it.
                position: "insideTopRight",
                fill: "var(--muted-foreground)",
                style: {
                  paintOrder: "stroke",
                  stroke: "var(--card)",
                  strokeWidth: 4,
                },
              }}
            />
            <Line
              type="monotone"
              dataKey="p95"
              stroke="var(--chart-1)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <table className="performance-trend-data">
        <caption>Dữ liệu xu hướng thời gian phản hồi</caption>
        <thead>
          <tr>
            <th scope="col">Mốc thời gian</th>
            <th scope="col">p95 (giây)</th>
            <th scope="col">p50 (giây)</th>
            <th scope="col">Lượt xử lý</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.label}-${index}`}>
              <th scope="row">{row.label}</th>
              <td>{formatSecondsValue(row.p95)}</td>
              <td>{formatSecondsValue(row.p50)}</td>
              <td>{row.turns.toLocaleString("vi-VN")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
};
