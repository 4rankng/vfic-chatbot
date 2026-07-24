import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
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

vi.mock("react-virtuoso", () => ({
  GroupedVirtuoso: ({
    data,
    groupContent,
    itemContent,
  }: {
    data: unknown[];
    groupContent: (index: number) => ReactNode;
    itemContent: (
      index: number,
      groupIndex: number,
      candidate: unknown,
    ) => ReactNode;
  }) => (
    <div data-testid="virtualized-candidate-list">
      {groupContent(0)}
      {data.map((candidate, index) => (
        <div key={index}>{itemContent(index, 0, candidate)}</div>
      ))}
    </div>
  ),
}));

import { RecruitingCommandCenter } from "./RecruitingCommandCenter";

const LocationProbe = () => {
  const location = useLocation();
  return (
    <output data-testid="dashboard-location">
      {location.pathname}
      {location.search}
    </output>
  );
};

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
          <LocationProbe />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    await expect
      .element(
        screen.getByRole("button", { name: /Mở hội thoại với Ứng viên mẫu/ }),
      )
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Mở hộp thư" }))
      .toBeVisible();
    await screen.getByRole("button", { name: "Mở hộp thư" }).click();
    await expect
      .element(screen.getByTestId("dashboard-location"))
      .toHaveTextContent("/conversations");
    await expect.element(screen.getByText("Quá hạn phản hồi")).toBeVisible();
    await expect.element(screen.getByText("Mở", { exact: true })).toBeVisible();
    expect(
      screen.container.querySelector(".dashboard-candidate-chevron"),
    ).toBeNull();
  });

  it("shows candidate identity and phone only, then opens the linked conversation", async () => {
    const attention = {
      updated_at: "2026-07-12T10:00:00Z",
      counters: {
        needs_reply: 0,
        overdue: 0,
        due_today: 0,
        priority: 0,
        unread: 0,
      },
      immediate: [],
      today: [],
    };
    mockApiJson.mockImplementation((url: string) =>
      Promise.resolve(
        url.startsWith("/api/v1/leads")
          ? {
              data: [
                {
                  id: 42,
                  zalo_id: "oa:user-42",
                  name: null,
                  phone: "0900000042",
                  avatar_url: null,
                  desired_job: "Công nhân sản xuất",
                  created_at: "2026-07-14T08:30:00Z",
                },
              ],
              total: 1,
            }
          : url.startsWith("/api/v1/conversations")
            ? {
                data: [
                  {
                    id: "conversation-42",
                    zalo_chat_id: "oa:user-42",
                    zalo_channel: "oa",
                    contact: {
                      display_name: "Phạm Hùng",
                      avatar_url: "https://example.com/pham-hung.jpg",
                    },
                  },
                ],
                total: 1,
              }
          : attention,
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <RecruitingCommandCenter />
          <LocationProbe />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    await expect.element(screen.getByText("Phạm Hùng")).toBeVisible();
    await expect.element(screen.getByText("0900000042")).toBeVisible();
    await expect
      .element(screen.getByAltText("Ảnh đại diện của Phạm Hùng"))
      .toHaveAttribute("src", "https://example.com/pham-hung.jpg");
    expect(screen.container.textContent).not.toContain("Công nhân sản xuất");
    expect(screen.container.textContent).not.toContain("15:30");

    await screen
      .getByRole("button", { name: /Chọn thao tác cho Phạm Hùng/ })
      .click();
    await expect
      .element(screen.getByRole("menuitem", { name: "Xem hội thoại" }))
      .toBeVisible();
    await screen
      .getByRole("menuitem", { name: "Dữ liệu ứng viên" })
      .click();
    await expect
      .element(screen.getByTestId("dashboard-location"))
      .toHaveTextContent(
        "/conversations?id=conversation-42&panel=candidate",
      );
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

  it("renders a candidate without a linked conversation as a non-clickable row", async () => {
    const attention = {
      updated_at: "2026-07-12T10:00:00Z",
      counters: {
        needs_reply: 0,
        overdue: 0,
        due_today: 0,
        priority: 0,
        unread: 0,
      },
      immediate: [],
      today: [],
    };
    mockApiJson.mockImplementation((url: string) =>
      Promise.resolve(
        url.startsWith("/api/v1/leads")
          ? {
              data: [
                {
                  id: 77,
                  zalo_id: null,
                  name: "Ứng viên tĩnh",
                  phone: "0900000077",
                  avatar_url: null,
                  desired_job: "Không được hiển thị",
                  created_at: "2026-07-14T08:30:00Z",
                },
              ],
              total: 1,
            }
          : attention,
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

    await expect.element(screen.getByText("Ứng viên tĩnh")).toBeVisible();
    expect(
      screen.container.querySelector(
        'button[aria-label^="Chọn thao tác cho Ứng viên tĩnh"]',
      ),
    ).toBeNull();
    expect(screen.container.textContent).not.toContain("Không được hiển thị");
  });

  it("keeps virtualized candidate rows clickable when the list exceeds 20 items", async () => {
    const candidates = Array.from({ length: 21 }, (_, index) => ({
      id: index + 1,
      zalo_id: `oa:user-${index + 1}`,
      name: `Ứng viên ${index + 1}`,
      phone: `09000000${String(index + 1).padStart(2, "0")}`,
      avatar_url: null,
      desired_job: null,
      created_at: `2026-07-14T08:${String(index).padStart(2, "0")}:00Z`,
    }));
    const conversations = candidates.map((candidate) => ({
      id: `conversation-${candidate.id}`,
      zalo_chat_id: candidate.zalo_id,
      zalo_channel: "oa",
      contact: null,
    }));
    mockApiJson.mockImplementation((url: string) =>
      Promise.resolve(
        url.startsWith("/api/v1/leads")
          ? { data: candidates, total: candidates.length }
          : url.startsWith("/api/v1/conversations/by-zalo-ids")
            ? { data: conversations, total: conversations.length }
            : {
                updated_at: "2026-07-12T10:00:00Z",
                counters: {
                  needs_reply: 0,
                  overdue: 0,
                  due_today: 0,
                  priority: 0,
                  unread: 0,
                },
                immediate: [],
                today: [],
              },
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <RecruitingCommandCenter />
          <LocationProbe />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    const firstRow = screen.getByRole("button", {
      name: /Chọn thao tác cho Ứng viên 21/,
    });
    await expect.element(firstRow).toBeVisible();
    await firstRow.click();
    await screen.getByRole("menuitem", { name: "Xem hội thoại" }).click();
    await expect
      .element(screen.getByTestId("dashboard-location"))
      .toHaveTextContent("/conversations?id=conversation-21");
  });
});
