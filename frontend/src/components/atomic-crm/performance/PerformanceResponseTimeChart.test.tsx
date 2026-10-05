import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "vitest-browser-react";

import "./performance.css";
import { PerformanceResponseTimeChart } from "./PerformanceResponseTimeChart";
import type { PerfTrendBucket, PerfWindow } from "./usePerformanceStats";

const trend: PerfTrendBucket[] = [
  {
    bucket: "2026-07-12T08:00:00+07:00",
    p95_ms: 3200,
    p50_ms: 1500,
    turns: 12,
  },
  // A bucket the backend could not stamp: the line keeps a gap, the table a dash.
  { bucket: null, p95_ms: null, p50_ms: null, turns: 0 },
  {
    bucket: "2026-07-12T09:00:00+07:00",
    p95_ms: 11800,
    p50_ms: 2400,
    turns: 7,
  },
];

// ResponsiveContainer measures its parent, so the test supplies the box the
// page's `.performance-chart` rule supplies in the app (280px tall, full width).
const renderChart = (data: PerfTrendBucket[], window: PerfWindow = "1d") =>
  render(
    <div style={{ width: "800px", height: "280px" }}>
      <PerformanceResponseTimeChart trend={data} window={window} />
    </div>,
  );

afterEach(async () => {
  await cleanup();
});

describe("PerformanceResponseTimeChart", () => {
  it("plots the trend and mirrors every bucket into the clipped table", async () => {
    const screen = await renderChart(trend);

    await expect
      .poll(() => screen.container.querySelector(".performance-chart svg"))
      .not.toBeNull();

    const table = screen.container.querySelector(".performance-trend-data");
    expect(table?.querySelector("caption")?.textContent).toBe(
      "Dữ liệu xu hướng thời gian phản hồi",
    );
    const rows = Array.from(table?.querySelectorAll("tbody tr") ?? []);
    expect(rows.map((row) => row.textContent)).toEqual([
      "08:003,21,512",
      "Chưa có——0",
      "09:0011,82,47",
    ]);
  });

  it("stamps the date on buckets for windows bucketed by day or week", async () => {
    const screen = await renderChart(trend, "1m");

    const label = screen.container.querySelector(
      ".performance-trend-data tbody th",
    );
    expect(label?.textContent).toMatch(/08:00.*12[-/]07/);
  });

  it("reports an empty window instead of an empty chart", async () => {
    const screen = await renderChart([]);

    await expect
      .element(screen.getByText("Chưa có dữ liệu trong khoảng thời gian này."))
      .toBeVisible();
    expect(screen.container.querySelector(".performance-chart")).toBeNull();
    expect(
      screen.container.querySelector(".performance-trend-data"),
    ).toBeNull();
  });
});
