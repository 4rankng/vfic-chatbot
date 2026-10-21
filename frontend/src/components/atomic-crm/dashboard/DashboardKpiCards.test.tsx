import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getDashboardMetrics: vi.fn(),
}));

vi.mock("../reporting/reportingService", () => ({
  getDashboardMetrics: mocks.getDashboardMetrics,
}));

import { DashboardKpiCards } from "./DashboardKpiCards";
import type { DashboardCandidate } from "./candidateDashboard";

const candidate = (
  overrides: Partial<DashboardCandidate> = {},
): DashboardCandidate => ({
  id: 1,
  zalo_id: "z-1",
  name: "Nguyễn Thị Mai",
  phone: "0912345678",
  avatar_url: null,
  conversation_id: "c-1",
  // Far in the past: outside both comparison windows on any run date, so the
  // derived trend figures stay deterministic.
  created_at: "2020-01-01T09:00:00+07:00",
  lead: {
    id: 1,
    zalo_id: "z-1",
    name: "Nguyễn Thị Mai",
    phone: "0912345678",
    desired_job: "Nhân viên kinh doanh",
    expected_salary: "12 triệu",
    lead_score: null,
    lead_stage: "NEW",
    created_at: "2020-01-01T09:00:00+07:00",
    updated_at: "2020-01-01T09:00:00+07:00",
  },
  ...overrides,
});

const METRICS = {
  total_leads: 84,
  hired_rate: 25,
  open_conversations: 7,
  unread_conversation_count: 2,
  stage_breakdown: [
    { value: "NEW", count: 34, percentage: 40 },
    { value: "CONTACTING", count: 29, percentage: 35 },
    { value: "REGISTERED", count: 21, percentage: 25 },
    { value: "SKIPPED", count: 0, percentage: 0 },
  ],
};

const renderCards = async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardKpiCards
        candidates={[candidate()]}
        counters={{
          needs_reply: 4,
          overdue: 2,
          due_today: 3,
          priority: 5,
          unread: 3,
        }}
      />
    </QueryClientProvider>,
  );
};

describe("DashboardKpiCards", () => {
  afterEach(async () => {
    await cleanup();
    mocks.getDashboardMetrics.mockReset();
  });

  it("renders the four KPI cards pipeline → new leads → conversion → open conversations", async () => {
    mocks.getDashboardMetrics.mockResolvedValue(METRICS);
    const screen = await renderCards();

    const list = screen.getByRole("region", { name: "Chỉ số nhanh" });
    await expect.element(list).toBeVisible();
    await expect.element(screen.getByText("Pipeline ứng viên")).toBeVisible();
    await expect
      .element(screen.getByText("Ứng viên mới (7 ngày)"))
      .toBeVisible();
    await expect.element(screen.getByText("Tỷ lệ chuyển đổi")).toBeVisible();
    await expect.element(screen.getByText("Hội thoại đang mở")).toBeVisible();
  });

  it("shows the stage mix caption and the open-conversation urgency counts", async () => {
    mocks.getDashboardMetrics.mockResolvedValue(METRICS);
    const screen = await renderCards();

    await expect
      .element(screen.getByText("Mới 34 · Đang liên hệ 29 · Đã đăng ký 21"))
      .toBeVisible();
    await expect
      .element(screen.getByText("4 cần phản hồi · 2 cần người xử lý"))
      .toBeVisible();
    const region = screen.getByRole("region", { name: "Chỉ số nhanh" });
    await expect.element(region).toHaveTextContent(/Pipeline ứng viên\s*84/);
    await expect
      .element(region)
      .toHaveTextContent(/Hội thoại đang mở\s*7\s*4 cần phản hồi/);
  });

  it("shows '—' instead of a fabricated conversion trend without cohort rows", async () => {
    mocks.getDashboardMetrics.mockResolvedValue(METRICS);
    const screen = await renderCards();

    // The single fixture lead sits outside both comparison windows, so the
    // conversion trend degrades to the em dash while growth reads 0%.
    await expect.element(screen.getByText("—")).toBeVisible();
    await expect
      .element(screen.getByRole("region", { name: "Chỉ số nhanh" }))
      .toHaveTextContent(/0%\s*so với 7 ngày trước/);
    await expect
      .element(screen.getByText("so với kỳ trước (7 ngày)"))
      .toBeVisible();
  });
});
