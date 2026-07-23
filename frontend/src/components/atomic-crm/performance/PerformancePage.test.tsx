import { describe, expect, it } from "vitest";
import { render } from "vitest-browser-react";

import type { PerfMetrics, PerfSlowTurn } from "./usePerformanceStats";
import { PerformanceMetrics } from "./PerformancePage";

const emptyMetrics: PerfMetrics = {
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

const slowTurn: PerfSlowTurn = {
  id: 42,
  conversation_id: "conversation-42",
  started_at: "2026-07-23T10:00:00Z",
  outcome: "SENT",
  lane: "agent",
  intent: "recruitment",
  llm_queue_ms: 100,
  llm_model_ms: 2_400,
  llm_backoff_ms: 0,
  llm_calls: 1,
  llm_call_ms: [2_400],
  tool_calls: 1,
  tool_ms: 200,
  tool_breakdown: null,
  prompt_tokens: 1_000,
  completion_tokens: 200,
  cached_tokens: 0,
  retried_429: false,
  degraded: false,
  prefetch_hit: true,
  pipeline_ms: 3_000,
  total_ms: 3_200,
  queue_depth: 0,
  outbound_adapter: "zalo_oa",
  outbound_prepare_ms: 20,
  outbound_provider_ms: 180,
  outbound_provider_attempts: 1,
  outbound_retry_count: 0,
  outbound_retry_ms: 0,
  outbound_refresh_count: 0,
  outbound_refresh_ms: 0,
  outbound_chunk_count: 1,
  outbound_result: "SENT",
  db_ms: 80,
  db_breakdown: null,
  faq_bypass_ms: 0,
  model_tier: "fast",
  system_prompt_cache_hit: true,
  dark_time_ms: 120,
};

const populatedMetrics: PerfMetrics = {
  ...emptyMetrics,
  percentiles: {
    end_to_end: { p50: 2_800, p95: 3_200, p99: 3_400 },
    llm_model: { p50: 2_000, p95: 2_400, p99: 2_500 },
  },
  by_lane: { agent: 1 },
  by_outcome: { SENT: 1 },
  by_adapter: [
    {
      adapter: "zalo_oa",
      turns: 1,
      sent: 1,
      unsent: 0,
      provider_p50_ms: 180,
      provider_p95_ms: 180,
      end_to_end_p50_ms: 3_200,
      end_to_end_p95_ms: 3_200,
      retry_count: 0,
      refresh_count: 0,
    },
  ],
  slow_turns: [slowTurn],
  trend: [
    {
      bucket: "2026-07-23T10:00:00Z",
      p95_ms: 3_200,
      p50_ms: 2_800,
      turns: 1,
      errors: 0,
    },
  ],
};

const manySlowTurns = Array.from({ length: 10 }, (_, index) => ({
  ...slowTurn,
  id: index + 1,
  conversation_id: `conversation-${index + 1}`,
}));

describe("PerformanceMetrics", () => {
  it("replaces repeated empty panels with one concise low-data state", async () => {
    const screen = await render(<PerformanceMetrics data={emptyMetrics} />);

    await expect
      .element(
        screen.getByRole("heading", {
          name: "Chưa có lượt xử lý trong 24 giờ",
        }),
      )
      .toBeVisible();
    expect(
      screen.container.querySelectorAll(".performance-metric"),
    ).toHaveLength(6);
    expect(
      screen.container.querySelector(".performance-primary-grid"),
    ).toBeNull();
    expect(screen.container.querySelector(".performance-details")).toBeNull();
    expect(screen.container.textContent).not.toContain(
      "Chưa có dữ liệu xu hướng",
    );
    expect(screen.container.textContent).not.toContain(
      "Chưa có dữ liệu theo kênh",
    );
  });

  it("keeps deep diagnostics collapsed until the operator asks for them", async () => {
    const screen = await render(<PerformanceMetrics data={populatedMetrics} />);
    const details = screen.container.querySelector<HTMLDetailsElement>(
      ".performance-details",
    );

    await expect
      .element(
        screen.getByRole("heading", {
          name: "Xu hướng độ trễ ứng viên chờ",
        }),
      )
      .toBeVisible();
    await expect
      .element(screen.getByRole("heading", { name: /Lượt cần xem/ }))
      .toBeVisible();
    expect(details?.open).toBe(false);
    expect(details?.querySelector(".tt-card")).toBeNull();

    await screen.getByText("Phân tích chi tiết", { exact: true }).click();

    expect(details?.open).toBe(true);
    await expect
      .element(
        screen.getByRole("heading", {
          name: "Chẩn đoán độ trễ",
        }),
      )
      .toBeVisible();
    await expect
      .element(
        screen.getByRole("heading", {
          name: "So sánh kênh giao gửi",
        }),
      )
      .toBeVisible();
  });

  it("keeps the slow-turn list short until more rows are requested", async () => {
    const screen = await render(
      <PerformanceMetrics
        data={{
          ...populatedMetrics,
          by_outcome: { SENT: manySlowTurns.length },
          slow_turns: manySlowTurns,
        }}
      />,
    );

    expect(
      screen.container.querySelectorAll(
        ".performance-slow-turns tbody > tr:not(.performance-detail-row)",
      ),
    ).toHaveLength(8);

    await screen
      .getByRole("button", { name: "Xem thêm 2 lượt", exact: true })
      .click();

    await expect
      .poll(
        () =>
          screen.container.querySelectorAll(
            ".performance-slow-turns tbody > tr:not(.performance-detail-row)",
          ).length,
      )
      .toBe(10);
    await expect
      .element(screen.getByRole("button", { name: "Thu gọn", exact: true }))
      .toBeVisible();
  });
});
