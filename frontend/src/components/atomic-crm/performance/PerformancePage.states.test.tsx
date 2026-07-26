import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "vitest-browser-react";

import type { PerfMetrics } from "./usePerformanceStats";
const usePerformanceStatsMock = vi.hoisted(() => vi.fn());
const navigateMock = vi.hoisted(() => vi.fn());

vi.mock(import("./usePerformanceStats"), () => ({
  usePerformanceStats: usePerformanceStatsMock,
}));

vi.mock(import("react-router-dom"), () => ({
  useNavigate: () => navigateMock,
}));

import { PerformancePage } from "./PerformancePage";

const metrics: PerfMetrics = {
  window: "24h",
  live: {
    queue_depth: 0,
    busy_workers: 0,
    total_workers: 2,
    llm_avg_latency_ms: 0,
    llm_invokes_last_2m: 0,
    minimax_429s_last_1m: 0,
  },
  percentiles: {},
  by_lane: {},
  by_outcome: {},
  by_adapter: [],
  slow_turns: [],
  trend: [],
  reliability: {
    send_unknown_count: 0,
    suppressed_count: 0,
    failed_count: 0,
  },
};

describe("PerformancePage wrapper states", () => {
  beforeEach(() => {
    usePerformanceStatsMock.mockReset();
    navigateMock.mockReset();
  });

  it("shows the loading state while the selected window is fetching", async () => {
    usePerformanceStatsMock.mockReturnValue({
      data: undefined,
      isPending: true,
      isError: false,
      refetch: vi.fn(),
      dataUpdatedAt: 0,
    });

    const screen = await render(<PerformancePage />);

    await expect
      .element(
        screen.getByRole("heading", { name: "Hiệu suất chatbot" }),
      )
      .toBeVisible();
    await expect
      .element(
        screen.getByLabelText("Đang tải số liệu hiệu suất"),
      )
      .toBeVisible();
    expect(screen.container.querySelector(".performance-skeletons")).not.toBeNull();
    expect(
      screen.container
        .querySelector(".performance-page")
        ?.getAttribute("aria-busy"),
    ).toBe("true");
  });

  it("shows the error state and lets the operator retry", async () => {
    const refetch = vi.fn();
    usePerformanceStatsMock.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      refetch,
      dataUpdatedAt: 0,
    });

    const screen = await render(<PerformancePage />);

    await expect
      .element(
        screen.getByRole("heading", {
          name: "Không tải được số liệu hiệu suất",
        }),
      )
      .toBeVisible();

    await screen.getByRole("button", { name: "Thử lại" }).click();
    expect(refetch).toHaveBeenCalledTimes(1);

    await screen.getByRole("button", { name: "Về Tổng quan" }).click();
    expect(navigateMock).toHaveBeenCalledWith("/");
  });

  it("refreshes and switches windows when data is available", async () => {
    const refetch = vi.fn();
    usePerformanceStatsMock.mockImplementation((windowKey: string) => ({
      data: { ...metrics, window: windowKey as PerfMetrics["window"] },
      isPending: false,
      isError: false,
      refetch,
      dataUpdatedAt: Date.parse("2026-07-26T20:00:00+08:00"),
    }));

    const screen = await render(<PerformancePage />);

    await expect
      .element(
        screen.getByRole("button", { name: /Cập nhật lúc/ }),
      )
      .toBeVisible();
    await expect
      .element(
        screen.getByRole("heading", {
          name: "Chưa có lượt xử lý trong 24 giờ",
        }),
      )
      .toBeVisible();

    await screen.getByRole("button", { name: "7 ngày" }).click();
    await expect
      .poll(() => usePerformanceStatsMock.mock.calls.at(-1)?.[0])
      .toBe("7d");
    await expect
      .element(
        screen.getByRole("heading", {
          name: "Chưa có lượt xử lý trong 7 ngày",
        }),
      )
      .toBeVisible();

    await screen.getByRole("button", { name: /Cập nhật lúc/ }).click();
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
