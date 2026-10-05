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
    return (
      <p className="performance-empty">
        Chưa có dữ liệu trong khoảng thời gian này.
      </p>
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
              label="10 giây"
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
