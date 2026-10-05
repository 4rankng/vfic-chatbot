import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "vitest-browser-react";

import { PerformanceMetrics } from "./PerformancePage";
import type { PerfMetrics } from "./usePerformanceStats";

const metrics: PerfMetrics = {
  window: "7d",
  response_time: {
    p50_ms: 1500,
    p95_ms: 3200,
    trend: [
      {
        bucket: "2026-07-12T08:00:00+07:00",
        p50_ms: 1500,
        p95_ms: 3200,
        turns: 12,
      },
    ],
  },
  conversion: { rate_pct: 25.0, with_phone: 3, candidate_chats: 12 },
};

afterEach(async () => {
  await cleanup();
});

describe("PerformanceMetrics", () => {
  it("shows the response time and the phone-capture rate", async () => {
    const screen = await render(
      <div style={{ width: "900px", height: "400px" }}>
        <PerformanceMetrics data={metrics} />
      </div>,
    );

    await expect
      .element(screen.getByRole("heading", { name: "Thời gian phản hồi" }))
      .toBeVisible();
    await expect
      .element(
        screen.getByRole("heading", { name: "Tỷ lệ thu được số điện thoại" }),
      )
      .toBeVisible();

    // p95 in seconds (Vietnamese decimal comma), p50 on the sub-line.
    await expect.element(screen.getByText("3,2 giây")).toBeVisible();
    await expect.element(screen.getByText("p50 1,5 giây")).toBeVisible();
    // The rate and the two raw counters that produced it.
    await expect.element(screen.getByText("25%")).toBeVisible();
    await expect
      .element(screen.getByText("3 / 12 cuộc trò chuyện"))
      .toBeVisible();
    // The Tailwind utility layer is not emitted in this project, so the bar has
    // no painted height; pin the value it carries instead (`ProgressBarBase`).
    expect(
      screen.container
        .querySelector(".performance-conversion-meter")
        ?.getAttribute("aria-valuenow"),
    ).toBe("25");

    const trendRows = screen.container.querySelectorAll(
      ".performance-trend-data tbody tr",
    );
    expect(trendRows).toHaveLength(1);
    expect(trendRows[0]?.textContent).toBe("08:003,21,512");
  });

  it("reports an unknown rate and no conversations instead of a zero bar", async () => {
    const screen = await render(
      <div style={{ width: "900px", height: "400px" }}>
        <PerformanceMetrics
          data={{
            ...metrics,
            response_time: { p50_ms: null, p95_ms: null, trend: [] },
            conversion: { rate_pct: null, with_phone: 0, candidate_chats: 0 },
          }}
        />
      </div>,
    );

    // Both headline numbers are unknown, not zero.
    expect(
      Array.from(
        screen.container.querySelectorAll(".performance-metric-value"),
      ).map((value) => value.textContent),
    ).toEqual(["—", "—"]);
    await expect
      .element(
        screen.getByText(
          "Chưa có cuộc trò chuyện nào từ ứng viên trong khoảng thời gian này.",
        ),
      )
      .toBeVisible();
    await expect
      .element(screen.getByText("Chưa có dữ liệu trong khoảng thời gian này."))
      .toBeVisible();
    expect(screen.container.querySelector('[role="progressbar"]')).toBeNull();
  });
});
