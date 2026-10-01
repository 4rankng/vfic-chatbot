import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  identity: { id: "admin-1" },
  getConversationBotRuns: vi.fn(),
  getBotRunTrace: vi.fn(),
}));

vi.mock("ra-core", () => ({
  // The component under test reads its labels from the Vietnamese catalog.
  useTranslate: () => testI18nProvider.translate,
  useDataProvider: () => ({
    getConversationBotRuns: mocks.getConversationBotRuns,
    getBotRunTrace: mocks.getBotRunTrace,
  }),
  useGetIdentity: () => ({ identity: mocks.identity }),
}));

import {
  DecisionTraceAction,
  DecisionTracePanel,
  DecisionTraceRenderer,
} from "./DecisionTracePanel";
import { DECISION_TRACE_QUERY_KEY } from "./decisionTraceQueries";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

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
  it("supports an external menu trigger and restores focus when closed", async () => {
    mocks.getConversationBotRuns.mockResolvedValue({ data: [], total: 0 });
    const queryClient = createQueryClient();

    const ControlledPanel = () => {
      const [open, setOpen] = useState(false);
      const triggerRef = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>
            Mở Suy luận chatbot
          </button>
          <DecisionTracePanel
            conversationId="conversation-1"
            open={open}
            onOpenChange={setOpen}
            showTrigger={false}
            returnFocusRef={triggerRef}
          />
        </>
      );
    };

    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ControlledPanel />
      </QueryClientProvider>,
    );
    const trigger = screen.getByRole("button", { name: "Mở Suy luận chatbot" });

    expect(mocks.getConversationBotRuns).not.toHaveBeenCalled();
    await trigger.click();
    await expect
      .poll(() => mocks.getConversationBotRuns.mock.calls.length)
      .toBe(1);
    await expect
      .element(screen.getByText("Chưa có lần chạy chatbot nào để hiển thị."))
      .toBeVisible();

    await screen.getByRole("button", { name: "Đóng" }).click();
    await expect.element(trigger).toHaveFocus();
    expect(
      queryClient.getQueriesData({ queryKey: DECISION_TRACE_QUERY_KEY }),
    ).toHaveLength(0);
  });

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
      name: "Suy luận chatbot",
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
      screen.container.querySelector('[aria-label="Suy luận chatbot"]'),
    ).toBeNull();
  });

  it("loads detail only on expansion and does not present legacy execution events as thinking", async () => {
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

    await screen.getByRole("button", { name: "Suy luận chatbot" }).click();
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
      .element(
        screen.getByText(
          "Lần chạy này không có dữ liệu suy luận do nhà cung cấp trả về.",
        ),
      )
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
  it("renders provider-returned reasoning and tool choices for every model turn", async () => {
    const screen = await render(
      <DecisionTraceRenderer
        trace={{
          version: 2,
          truncated: false,
          events: [
            {
              seq: 1,
              kind: "model_turn",
              turn: 1,
              phase: "tool_request",
              provider: "minimax",
              model: "MiniMax-M2.7",
              reasoning_status: "returned",
              reasoning: "Cần kiểm tra dữ liệu tuyển dụng hiện tại.",
              tool_names: ["search_knowledge"],
            },
            {
              seq: 2,
              kind: "model_turn",
              turn: 2,
              phase: "final",
              provider: "minimax",
              model: "MiniMax-M2.7",
              reasoning_status: "not_returned",
              reasoning: null,
              tool_names: [],
            },
            {
              seq: 3,
              kind: "model_turn",
              turn: 3,
              phase: "direct",
              provider: "openrouter",
              model: "deepseek/deepseek-v4-flash",
              reasoning_status: "truncated",
              reasoning: "Returned reasoning was capped.",
              tool_names: [],
            },
          ],
        }}
      />,
    );

    await expect.element(screen.getByText("Lượt suy luận 1")).toBeVisible();
    await expect
      .element(screen.getByText("Cần kiểm tra dữ liệu tuyển dụng hiện tại."))
      .not.toBeVisible();
    await screen
      .getByLabelText(
        /^Chi tiết lượt suy luận 1: .*minimax.*MiniMax-M2\.7.*1 công cụ$/,
      )
      .click();
    await expect
      .element(screen.getByText("Cần kiểm tra dữ liệu tuyển dụng hiện tại."))
      .toBeVisible();
    await expect
      .element(screen.getByText("Tra cứu cơ sở kiến thức"))
      .toBeVisible();
    await screen
      .getByLabelText(/^Chi tiết lượt suy luận 2: .*minimax.*MiniMax-M2\.7$/)
      .click();
    await expect
      .element(
        screen.getByText(
          "Nhà cung cấp không trả về nội dung suy luận cho lượt này.",
        ),
      )
      .toBeVisible();
    await screen
      .getByLabelText(
        /^Chi tiết lượt suy luận 3: .*openrouter.*deepseek\/deepseek-v4-flash$/,
      )
      .click();
    await expect
      .element(screen.getByText("Suy luận · đã rút gọn"))
      .toBeVisible();
    expect(
      screen.container.querySelectorAll(".decision-trace-reasoning"),
    ).toHaveLength(2);
    expect(
      screen.container.querySelector(".decision-trace-reasoning.rounded-md"),
    ).toBeNull();
  });

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
