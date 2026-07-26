import { render } from "vitest-browser-react";
import { describe, expect, it } from "vitest";

import { formatMetricDuration } from "../reporting/domain/performanceDiagnostics";
import { PerformanceTrendChart } from "./PerformanceTrendChart";
import { formatTrendBucket } from "./trendAxis";
import type { PerfTrendBucket } from "./usePerformanceStats";

const mixedTrend: PerfTrendBucket[] = [
  {
    bucket: "2026-07-23T10:00:00Z",
    p95_ms: 3_200,
    p50_ms: 2_800,
    turns: 2,
    errors: 0,
  },
  {
    bucket: "2026-07-23T10:05:00Z",
    p95_ms: 15_000,
    p50_ms: 8_200,
    turns: 3,
    errors: 0,
  },
  {
    bucket: "2026-07-23T10:10:00Z",
    p95_ms: 25_000,
    p50_ms: 14_000,
    turns: 4,
    errors: 0,
  },
  {
    bucket: "2026-07-23T10:15:00Z",
    p95_ms: null,
    p50_ms: null,
    turns: 1,
    errors: 0,
  },
  {
    bucket: "2026-07-23T10:20:00Z",
    p95_ms: 5_500,
    p50_ms: 3_100,
    turns: 5,
    errors: 2,
  },
];

describe("PerformanceTrendChart", () => {
  it("renders the low-data empty state when no trend buckets exist", async () => {
    const screen = await render(
      <PerformanceTrendChart trend={[]} window="24h" />,
    );

    await expect
      .element(screen.getByText("Chưa có dữ liệu xu hướng."))
      .toBeVisible();
    expect(screen.container.querySelector(".performance-trend")).toBeNull();
    expect(screen.container.querySelector("table")).toBeNull();
  });

  it("renders the accessible trend table, axis labels, and every bar tone branch", async () => {
    const screen = await render(
      <PerformanceTrendChart trend={mixedTrend} window="7d" />,
    );
    const trendTable = screen.getByRole("table", {
      name: "Dữ liệu xu hướng độ trễ ứng viên chờ",
    });

    await expect.element(trendTable).toBeInTheDocument();
    await expect
      .element(
        trendTable.getByText(
          formatTrendBucket(mixedTrend[0]?.bucket ?? null, true),
        ),
      )
      .toBeInTheDocument();
    await expect
      .element(
        trendTable.getByText(
          formatMetricDuration(mixedTrend[0]?.p95_ms ?? null),
        ),
      )
      .toBeInTheDocument();
    await expect
      .element(
        screen.getByText(
          "2 lượt lỗi cần đối chiếu với các phiên vượt ngưỡng.",
        ),
      )
      .toBeVisible();

    expect(
      screen.container.querySelectorAll(".performance-trend-bar.is-success"),
    ).toHaveLength(1);
    expect(
      screen.container.querySelectorAll(".performance-trend-bar.is-warning"),
    ).toHaveLength(1);
    expect(
      screen.container.querySelectorAll(".performance-trend-bar.is-error"),
    ).toHaveLength(1);
    expect(
      screen.container.querySelectorAll(".performance-trend-bar"),
    ).toHaveLength(5);
    expect(
      screen.container.querySelector(".performance-trend-axis .is-first"),
    ).not.toBeNull();
    expect(
      screen.container.querySelector(".performance-trend-axis .is-last"),
    ).not.toBeNull();
  });

  it("reports a clean note when the selected window has no errors", async () => {
    const screen = await render(
      <PerformanceTrendChart trend={[mixedTrend[0]!]} window="24h" />,
    );

    await expect
      .element(
        screen.getByText("Không ghi nhận lượt lỗi trong khoảng đã chọn."),
      )
      .toBeVisible();
  });
});
