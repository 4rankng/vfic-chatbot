import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "vitest-browser-react";

import type { PerfMetrics, PerfWindow } from "./usePerformanceStats";
const usePerformanceStatsMock = vi.hoisted(() => vi.fn());
const navigateMock = vi.hoisted(() => vi.fn());

vi.mock(import("./usePerformanceStats"), () => ({
  usePerformanceStats: usePerformanceStatsMock,
}));

vi.mock(import("react-router-dom"), () => ({
  useNavigate: () => navigateMock,
}));

import { PerformancePage } from "./PerformancePage";
import { TestMessages } from "@/components/atomic-crm/providers/commons/TestMessages";

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

const renderPage = () =>
  render(
    <TestMessages>
      <PerformancePage />
    </TestMessages>,
  );

describe("PerformancePage wrapper states", () => {
  beforeEach(() => {
    usePerformanceStatsMock.mockReset();
    navigateMock.mockReset();
  });

  it("shows the loading state while the selected window is fetching", async () => {
    usePerformanceStatsMock.mockReturnValue({
      data: undefined,
      isPending: true,
      isFetching: true,
      isError: false,
      refetch: vi.fn(),
      dataUpdatedAt: 0,
    });

    const screen = await renderPage();

    await expect
      .element(screen.getByRole("heading", { name: "Hiệu suất chatbot" }))
      .toBeVisible();
    const loading = screen.getByLabelText("Đang tải số liệu hiệu suất");
    await expect.element(loading).toBeVisible();
    expect(loading.element().getAttribute("role")).toBe("status");
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
      isFetching: false,
      isError: true,
      refetch,
      dataUpdatedAt: 0,
    });

    const screen = await renderPage();

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

  it("keeps known metrics visible when a background refresh fails", async () => {
    usePerformanceStatsMock.mockReturnValue({
      data: metrics,
      isPending: false,
      isFetching: false,
      isError: true,
      refetch: vi.fn(),
      dataUpdatedAt: Date.parse("2026-07-26T20:00:00+08:00"),
    });

    const screen = await renderPage();

    await expect.element(screen.getByRole("alert")).toBeVisible();
    await expect
      .element(screen.getByRole("heading", { name: "Thời gian phản hồi" }))
      .toBeVisible();
    await expect
      .element(
        screen.getByRole("heading", {
          name: "Không tải được số liệu hiệu suất",
        }),
      )
      .not.toBeInTheDocument();
  });

  it("re-requests the stats for each of the five periods", async () => {
    const refetch = vi.fn();
    usePerformanceStatsMock.mockImplementation((window: PerfWindow) => ({
      data: { ...metrics, window },
      isPending: false,
      isFetching: false,
      isError: false,
      refetch,
      dataUpdatedAt: Date.parse("2026-07-26T20:00:00+08:00"),
    }));

    const screen = await renderPage();

    await expect
      .element(screen.getByRole("button", { name: /Cập nhật lúc/ }))
      .toBeVisible();

    const periods = [
      ["1 ngày", "1d"],
      ["7 ngày", "7d"],
      ["1 tháng", "1m"],
      ["3 tháng", "3m"],
      ["6 tháng", "6m"],
    ] as const;

    for (const [label, key] of periods) {
      await screen.getByRole("radio", { name: label }).click();
      await expect
        .poll(() => usePerformanceStatsMock.mock.calls.at(-1)?.[0])
        .toBe(key);
      // One segmented control: exactly the clicked period is marked selected.
      const selected = Array.from(
        screen.container.querySelectorAll<HTMLButtonElement>(
          '[aria-label="Khoảng thời gian"] button[data-selected]',
        ),
      );
      expect(selected.map((segment) => segment.textContent)).toEqual([label]);
    }

    await screen.getByRole("button", { name: /Cập nhật lúc/ }).click();
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("prevents overlapping refresh requests while metrics are fetching", async () => {
    const refetch = vi.fn();
    usePerformanceStatsMock.mockReturnValue({
      data: metrics,
      isPending: false,
      isFetching: true,
      isError: false,
      refetch,
      dataUpdatedAt: Date.parse("2026-07-26T20:00:00+08:00"),
    });

    const screen = await renderPage();

    await expect
      .element(screen.getByRole("button", { name: /Cập nhật lúc/ }))
      .toBeDisabled();
    expect(refetch).not.toHaveBeenCalled();
  });
});
