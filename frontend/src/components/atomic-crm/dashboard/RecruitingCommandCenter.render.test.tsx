import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";

const { mockApiJson } = vi.hoisted(() => ({
  mockApiJson: vi.fn(),
}));

vi.mock("../providers/rest/api", () => ({
  apiJson: mockApiJson,
}));

import { RecruitingCommandCenter } from "./RecruitingCommandCenter";

describe("RecruitingCommandCenter candidate rows", () => {
  it("opens a conversation without rendering a redundant chevron", async () => {
    mockApiJson.mockResolvedValueOnce({
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
    });
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

    await expect.element(
      screen.getByRole("button", { name: /Mở hội thoại với Ứng viên mẫu/ }),
    ).toBeVisible();
    expect(screen.container.querySelector(".dashboard-candidate-chevron")).toBeNull();
  });
});
