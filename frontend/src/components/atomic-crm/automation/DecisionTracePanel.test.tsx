import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  identity: { id: "admin-1" },
  getConversationBotRuns: vi.fn(),
  getBotRunTrace: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useDataProvider: () => ({
    getConversationBotRuns: mocks.getConversationBotRuns,
    getBotRunTrace: mocks.getBotRunTrace,
  }),
  useGetIdentity: () => ({ identity: mocks.identity }),
}));

import {
  DecisionTraceAction,
  DecisionTraceRenderer,
} from "./DecisionTracePanel";
import { DECISION_TRACE_QUERY_KEY } from "./decisionTraceQueries";

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
  mocks.identity = { id: "admin-1" };
});

describe("DecisionTraceAction", () => {
  it("shows the trigger only to administrators and does not fetch before open", async () => {
    mocks.getConversationBotRuns.mockResolvedValue({ data: [], total: 0 });
    const queryClient = createQueryClient();
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <DecisionTraceAction
          permissions="admin"
          conversationId="conversation-1"
        />
      </QueryClientProvider>,
    );

    const trigger = screen.getByRole("button", {
      name: "Dấu vết quyết định",
    });
    await expect.element(trigger).toBeVisible();
    expect(mocks.getConversationBotRuns).not.toHaveBeenCalled();

    await trigger.click();
    await expect
      .poll(() => mocks.getConversationBotRuns.mock.calls.length)
      .toBe(1);
    expect(mocks.getConversationBotRuns).toHaveBeenCalledWith("conversation-1");
    await expect
      .element(screen.getByText("Chưa có lần chạy chatbot nào để hiển thị."))
      .toBeVisible();

    await screen.getByRole("button", { name: "Đóng" }).click();
    await expect.element(trigger).toHaveFocus();
    expect(
      queryClient.getQueriesData({ queryKey: DECISION_TRACE_QUERY_KEY }),
    ).toHaveLength(0);

    await screen.rerender(
      <QueryClientProvider client={queryClient}>
        <DecisionTraceAction
          permissions="recruiter"
          conversationId="conversation-1"
        />
      </QueryClientProvider>,
    );
    expect(
      screen.container.querySelector('[aria-label="Dấu vết quyết định"]'),
    ).toBeNull();
  });

  it("loads detail only on expansion and renders legacy, truncated, and unknown codes safely", async () => {
    mocks.getConversationBotRuns.mockResolvedValue({
      data: [
        {
          id: 70,
          conversation_id: "conversation-1",
          started_at: "2026-07-18T10:00:00Z",
          ended_at: "2026-07-18T10:00:01Z",
          outcome: "sent",
          trace_available: false,
        },
        {
          id: 71,
          conversation_id: "conversation-1",
          started_at: "2026-07-18T10:01:00Z",
          ended_at: "2026-07-18T10:01:02Z",
          outcome: "suppressed",
          trace_available: true,
        },
      ],
      total: 2,
    });
    mocks.getBotRunTrace.mockResolvedValue({
      id: 71,
      conversation_id: "conversation-1",
      started_at: "2026-07-18T10:01:00Z",
      ended_at: "2026-07-18T10:01:02Z",
      outcome: "suppressed",
      trace_available: true,
      decision_trace: {
        version: 1,
        truncated: true,
        events: [
          {
            seq: 1,
            kind: "decision",
            code: "private-route-value",
            summary_code: "candidate-secret-summary",
          },
          {
            seq: 2,
            kind: "tool",
            name: "private-tool-name",
            selected_by: "model",
          },
        ],
      },
    });
    const screen = await render(
      <QueryClientProvider client={createQueryClient()}>
        <DecisionTraceAction
          permissions="admin"
          conversationId="conversation-1"
        />
      </QueryClientProvider>,
    );

    await screen.getByRole("button", { name: "Dấu vết quyết định" }).click();
    await expect.element(screen.getByText("Lần chạy #70")).toBeVisible();
    expect(mocks.getBotRunTrace).not.toHaveBeenCalled();

    await screen.getByText("Lần chạy #70").click();
    await expect
      .element(screen.getByText("Không có dấu vết cho lần chạy cũ này."))
      .toBeVisible();
    expect(mocks.getBotRunTrace).not.toHaveBeenCalled();

    await screen.getByText("Lần chạy #71").click();
    await expect.poll(() => mocks.getBotRunTrace.mock.calls.length).toBe(1);
    await expect
      .element(
        screen.getByText(
          "Dấu vết đã đạt giới hạn lưu trữ. Danh sách dưới đây có thể chưa đầy đủ.",
        ),
      )
      .toBeVisible();
    await expect
      .element(screen.getByText("Quyết định chưa được hỗ trợ"))
      .toBeVisible();
    await expect
      .element(screen.getByText("Công cụ chưa được hỗ trợ"))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("private-route-value");
    expect(screen.container.textContent).not.toContain(
      "candidate-secret-summary",
    );
    expect(screen.container.textContent).not.toContain("private-tool-name");
    expect(mocks.getBotRunTrace).toHaveBeenCalledWith(71);
  });
});

describe("DecisionTraceRenderer", () => {
  it("does not expose raw fields from unsupported trace versions", async () => {
    const screen = await render(
      <DecisionTraceRenderer
        trace={{
          version: 99,
          truncated: false,
          events: [
            {
              seq: 1,
              kind: "decision",
              code: "raw-private-code",
              summary_code: "raw-private-value",
            },
          ],
        }}
      />,
    );

    await expect
      .element(screen.getByText(/Phiên bản dấu vết này chưa được hỗ trợ/))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("raw-private-code");
    expect(screen.container.textContent).not.toContain("raw-private-value");
  });
});
