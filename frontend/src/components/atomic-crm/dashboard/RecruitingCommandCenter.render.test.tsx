import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";

const { mockApiJson } = vi.hoisted(() => ({
  mockApiJson: vi.fn(),
}));

vi.mock("@/lib/apiClient", () => ({
  apiJson: mockApiJson,
}));

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => false,
}));

import { RecruitingCommandCenter } from "./RecruitingCommandCenter";

describe("RecruitingCommandCenter candidate rows", () => {
  it("opens a conversation without rendering a redundant chevron", async () => {
    const attention = {
      updated_at: "2026-07-12T10:00:00Z",
      counters: {
        needs_reply: 1,
        overdue: 0,
        due_today: 0,
        priority: 0,
        unread: 0,
      },
      immediate: [
        {
          key: "candidate",
          reason: "REPLY_OVERDUE",
          urgency_at: "2026-07-12T09:00:00Z",
          conversation_id: "conversation-1",
          lead_id: null,
          name: "Ứng viên mẫu",
          phone: null,
          desired_job: null,
          lead_stage: null,
          lead_score: null,
          last_inbound_at: null,
          due_at: null,
          delivery_status: null,
          action: "OPEN_CONVERSATION",
        },
      ],
      today: [],
    };
    mockApiJson.mockImplementation((url: string) =>
      Promise.resolve(
        url.startsWith("/api/v1/leads") ? { data: [], total: 0 } : attention,
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <RecruitingCommandCenter />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    await expect
      .element(
        screen.getByRole("button", { name: /Mở hội thoại với Ứng viên mẫu/ }),
      )
      .toBeVisible();
    await expect.element(screen.getByText("Quá hạn phản hồi")).toBeVisible();
    expect(
      screen.container.querySelector(".dashboard-candidate-chevron"),
    ).toBeNull();
  });

  it("does not report an active queue while initial requests are failing", async () => {
    mockApiJson.mockRejectedValue(new Error("network unavailable"));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <RecruitingCommandCenter />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    await expect
      .element(screen.getByText("Đang chờ kết nối dữ liệu"))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain(
      "Hàng đợi đang hoạt động",
    );
  });
});
