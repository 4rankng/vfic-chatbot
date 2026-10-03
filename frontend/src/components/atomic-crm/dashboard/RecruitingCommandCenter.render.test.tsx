import type * as RaCore from "ra-core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  mockApiJson,
  mockDataProviderUpdate,
  mockNotify,
  mockPermissions,
  mockMobile,
} = vi.hoisted(() => ({
  mockApiJson: vi.fn(),
  mockDataProviderUpdate: vi.fn(),
  mockNotify: vi.fn(),
  mockPermissions: { value: "recruiter" },
  mockMobile: { value: false },
}));

vi.mock("@/lib/apiClient", () => ({
  apiJson: mockApiJson,
}));

vi.mock("ra-core", async (importOriginal) => {
  const actual = await importOriginal<typeof RaCore>();
  return {
    ...actual,
    useDataProvider: () => ({ update: mockDataProviderUpdate }),
    useNotify: () => mockNotify,
    usePermissions: () => ({ permissions: mockPermissions.value }),
  };
});

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => mockMobile.value,
}));

import { RecruitingCommandCenter } from "./RecruitingCommandCenter";
import "@/index.css";
import "./dashboard.css";
import { TestMessages } from "@/components/atomic-crm/providers/commons/TestMessages";

const LocationProbe = () => {
  const location = useLocation();
  return (
    <output data-testid="dashboard-location">
      {location.pathname}
      {location.search}
    </output>
  );
};

// `Promise.withResolvers` is ES2024 and this project targets ES2022, so the
// pending promise is built with an explicit resolver instead.
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
};

describe("RecruitingCommandCenter candidate rows", () => {
  beforeEach(() => {
    mockDataProviderUpdate.mockReset();
    mockDataProviderUpdate.mockResolvedValue({ data: {} });
    mockNotify.mockReset();
    mockPermissions.value = "recruiter";
    mockMobile.value = false;
  });

  afterEach(async () => {
    await cleanup();
    await page.viewport(1280, 900);
  });

  it.each([1280, 320, 390])(
    "keeps the attention row readable and its placeholder unboxed at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      mockMobile.value = width < 768;
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
        <TestMessages>
          <MemoryRouter>
            <QueryClientProvider client={queryClient}>
              <div className="dashboard-workspace">
                <section className="dashboard-workspace-content uu-scope">
                  <RecruitingCommandCenter />
                </section>
              </div>
              <LocationProbe />
            </QueryClientProvider>
          </MemoryRouter>
        </TestMessages>,
      );

      await expect
        .element(
          screen.getByRole("button", { name: /Mở hội thoại với Ứng viên mẫu/ }),
        )
        .toBeVisible();
      await expect
        .element(screen.getByLabelText("1 hội thoại cần xử lý"))
        .toBeVisible();
      await expect.element(screen.getByText("Quá hạn phản hồi")).toBeVisible();
      await expect
        .element(screen.getByText("Mở", { exact: true }))
        .toBeVisible();
      expect(
        screen.container.querySelector(".dashboard-candidate-chevron"),
      ).toBeNull();
      const row = screen.container.querySelector<HTMLElement>(
        ".dashboard-candidate-row",
      )!;
      const rowBox = row.getBoundingClientRect();
      const icon = row.querySelector<HTMLElement>(
        ".dashboard-candidate-avatar-content",
      )!;
      expect(icon.querySelector("svg")).not.toBeNull();
      expect(getComputedStyle(icon).backgroundColor).toBe("rgba(0, 0, 0, 0)");
      expect(getComputedStyle(icon).outlineWidth).toBe("0px");
      expect(getComputedStyle(icon).borderTopWidth).toBe("0px");
      if (width < 768) {
        expect(rowBox.height).toBeGreaterThanOrEqual(60);
        expect(rowBox.right).toBeLessThanOrEqual(width);
        for (const content of row.children) {
          const box = content.getBoundingClientRect();
          expect(box.top).toBeGreaterThanOrEqual(rowBox.top);
          expect(box.bottom).toBeLessThanOrEqual(rowBox.bottom);
          expect(box.right).toBeLessThanOrEqual(rowBox.right);
        }
      }
    },
  );

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
                  years_experience: "2 năm",
                  version: 3,
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
      <TestMessages>
        <MemoryRouter>
          <QueryClientProvider client={queryClient}>
            <RecruitingCommandCenter />
            <LocationProbe />
          </QueryClientProvider>
        </MemoryRouter>
      </TestMessages>,
    );

    await expect.element(screen.getByText("Phạm Hùng")).toBeVisible();
    await expect.element(screen.getByText("0900000042")).toBeVisible();
    await expect
      .element(screen.getByLabelText("0 hội thoại cần xử lý"))
      .toBeVisible();
    await expect.element(screen.getByLabelText("1 ứng viên mới")).toBeVisible();
    const worklist = screen.container.querySelector(".recruiting-worklist");
    expect(worklist).not.toBeNull();
    expect(worklist?.querySelectorAll(".recruiting-panel")).toHaveLength(2);
    await expect
      .element(
        screen.getByRole("heading", {
          name: "THỨ BA, 14/07/2026",
          level: 3,
        }),
      )
      .toBeVisible();
    await expect
      .element(screen.getByText("Xem", { exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByAltText("Ảnh đại diện của Phạm Hùng"))
      .toHaveAttribute("src", "https://example.com/pham-hung.jpg");
    const candidateRow = screen.container.querySelector(
      ".recruiting-candidate-panel .dashboard-candidate-row",
    );
    expect(candidateRow).not.toBeNull();
    expect(candidateRow?.textContent).not.toContain("Công nhân sản xuất");
    expect(candidateRow?.textContent).not.toContain("15:30");
    expect(screen.container.textContent).not.toContain(
      "Hàng đợi đang thông thoáng",
    );
    expect(screen.container.textContent).not.toContain(
      "Không có hội thoại cần can thiệp",
    );
    expect(screen.container.textContent).not.toContain("Ưu tiên phản hồi");
    expect(screen.container.textContent).not.toContain("Luồng ứng viên");

    const rowButton = screen.getByRole("button", {
      name: /Mở hội thoại với Phạm Hùng/,
    });
    await rowButton.click();
    await expect
      .element(screen.getByTestId("dashboard-location"))
      .toHaveTextContent("/conversations?id=conversation-42");
  });

  it("does not report an active queue while initial requests are failing", async () => {
    mockApiJson.mockRejectedValue(new Error("network unavailable"));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <TestMessages>
        <MemoryRouter>
          <QueryClientProvider client={queryClient}>
            <RecruitingCommandCenter />
          </QueryClientProvider>
        </MemoryRouter>
      </TestMessages>,
    );

    await expect
      .element(screen.getByText("Không tải được hội thoại."))
      .toBeVisible();
    await expect
      .element(screen.getByText("Không tải được ứng viên."))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain(
      "Hàng đợi đang hoạt động",
    );
  });

  it("keeps both queue shells labelled while the first fetch is in flight", async () => {
    // A never-settling request leaves TanStack Query pending, so the panels
    // render their first-load placeholders rather than an empty queue.
    mockApiJson.mockImplementation(() => deferred<never>().promise);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <TestMessages>
        <MemoryRouter>
          <QueryClientProvider client={queryClient}>
            <RecruitingCommandCenter />
          </QueryClientProvider>
        </MemoryRouter>
      </TestMessages>,
    );

    await expect
      .element(screen.getByLabelText("Đang tải số hội thoại cần xử lý"))
      .toBeVisible();
    await expect
      .element(screen.getByLabelText("Đang tải số ứng viên mới"))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain(
      "Không tải được hội thoại.",
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
      <TestMessages>
        <MemoryRouter>
          <QueryClientProvider client={queryClient}>
            <RecruitingCommandCenter />
          </QueryClientProvider>
        </MemoryRouter>
      </TestMessages>,
    );

    await expect.element(screen.getByText("Ứng viên tĩnh")).toBeVisible();
    expect(
      screen.container.querySelector(
        'button[aria-label^="Mở hội thoại với Ứng viên tĩnh"]',
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
      <TestMessages>
        <MemoryRouter>
          <QueryClientProvider client={queryClient}>
            <RecruitingCommandCenter />
            <LocationProbe />
          </QueryClientProvider>
        </MemoryRouter>
      </TestMessages>,
    );

    const firstRow = screen.getByRole("button", {
      name: /Mở hội thoại với Ứng viên 21/,
    });
    await expect.element(firstRow).toBeVisible();
    // Virtualizing must not drop the day grouping: the header is its own list
    // item rendered above that day's rows.
    await expect
      .element(
        screen.getByRole("heading", { name: "THỨ BA, 14/07/2026", level: 3 }),
      )
      .toBeVisible();
    await firstRow.click();
    await expect
      .element(screen.getByTestId("dashboard-location"))
      .toHaveTextContent("/conversations?id=conversation-21");
  });

  it("renders both worklist queues as empty states when nothing needs action", async () => {
    mockApiJson.mockImplementation((url: string) =>
      Promise.resolve(
        url.startsWith("/api/v1/leads")
          ? { data: [], total: 0 }
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
      <TestMessages>
        <MemoryRouter>
          <QueryClientProvider client={queryClient}>
            <RecruitingCommandCenter />
          </QueryClientProvider>
        </MemoryRouter>
      </TestMessages>,
    );

    await expect
      .element(
        screen.getByRole("heading", { name: "Không có hội thoại cần xử lý" }),
      )
      .toBeVisible();
    await expect
      .element(
        screen.getByRole("heading", {
          name: "Chưa có ứng viên có số điện thoại",
        }),
      )
      .toBeVisible();
    // An empty queue is not a failed queue: the counts stay at zero and the
    // retry panes stay out of the worklist.
    await expect
      .element(screen.getByLabelText("0 hội thoại cần xử lý"))
      .toBeVisible();
    await expect.element(screen.getByLabelText("0 ứng viên mới")).toBeVisible();
    expect(screen.container.textContent).not.toContain(
      "Không tải được hội thoại.",
    );
    expect(screen.container.textContent).not.toContain(
      "Không tải được ứng viên.",
    );
  });
});
