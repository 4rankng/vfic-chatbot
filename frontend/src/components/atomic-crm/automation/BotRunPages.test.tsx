import { type ReactNode } from "react";
import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BotRun, BotRunTraceDetail } from "../types";

const mocks = vi.hoisted(() => ({
  redirect: vi.fn(),
  list: {
    data: [] as BotRun[],
    isPending: false,
  },
}));

vi.mock("ra-core", () => ({
  ListBase: ({ children }: { children: ReactNode }) => children,
  useDataProvider: () => ({}),
  useGetIdentity: () => ({ identity: { id: "admin-1" } }),
  useListContext: () => mocks.list,
  useRedirect: () => mocks.redirect,
}));

vi.mock("@/components/admin/list-pagination", () => ({
  ListPagination: ({ className }: { className?: string }) => (
    <nav className={className} aria-label="Phân trang">
      Phân trang
    </nav>
  ),
}));

import { BotRunListContent } from "./BotRunList";
import { BotRunShowContent } from "./BotRunShow";

const run: BotRun = {
  id: 42,
  conversation_id: "conversation-42",
  started_at: "2026-07-23T10:00:00Z",
  ended_at: "2026-07-23T10:00:02Z",
  version_at_start: 3,
  proposed_reply:
    "Đây là câu trả lời dài chỉ nên xuất hiện ở phần xem trước, không nằm trong tên truy cập của cả hàng.",
  outcome: "sent",
};

describe("Bot run pages", () => {
  beforeEach(() => {
    mocks.redirect.mockReset();
    mocks.list = { data: [run], isPending: false };
  });

  it("keeps the list flat, concise and inside the shared scroll owner", async () => {
    const screen = await render(<BotRunListContent />);
    const row = screen.getByRole("button", {
      name: /Xem lần chạy #42: Đã gửi/,
    });
    const section = screen.getByRole("region", { name: "Nhật ký xử lý" });
    const shell = screen.container.querySelector<HTMLElement>(".tt-page-shell");
    const pagination = screen.getByRole("navigation", { name: "Phân trang" });

    await expect.element(row).toBeVisible();
    expect(row.element().getAttribute("aria-label")).not.toContain(
      "Đây là câu trả lời dài",
    );
    expect(section.element().querySelector(".overflow-y-auto")).toBeNull();
    expect(screen.container.querySelector(".tt-alternate-card")).toBeNull();
    expect(shell).toHaveClass("h-full", "min-h-0", "overflow-y-auto");
    expect(shell?.contains(pagination.element())).toBe(true);

    await row.click();
    expect(mocks.redirect).toHaveBeenCalledWith("show", "bot_runs", 42);
  });

  it("shows run facts and the decision trace without nested cards", async () => {
    const detail: BotRunTraceDetail = {
      id: 42,
      conversation_id: "conversation-42",
      started_at: "2026-07-23T10:00:00Z",
      ended_at: "2026-07-23T10:00:02Z",
      outcome: "sent",
      trace_available: true,
      decision_trace: {
        version: 2,
        truncated: false,
        events: [
          {
            seq: 1,
            kind: "model_turn",
            turn: 1,
            phase: "final",
            provider: "minimax",
            model: "MiniMax-M2.7",
            reasoning_status: "returned",
            reasoning: "Đã kiểm tra dữ liệu trước khi trả lời.",
            tool_names: [],
          },
        ],
      },
    };
    const screen = await render(<BotRunShowContent run={detail} />);

    await expect
      .element(
        screen.getByRole("heading", {
          name: "Lần chạy bot #42",
        }),
      )
      .toBeVisible();
    await expect.element(screen.getByText("conversation-42")).toBeVisible();
    await expect.element(screen.getByText("2.0 giây")).toBeVisible();
    await expect
      .element(screen.getByRole("heading", { name: "Dấu vết quyết định" }))
      .toBeVisible();
    await expect
      .element(screen.getByText("Đã kiểm tra dữ liệu trước khi trả lời."))
      .toBeVisible();
    expect(screen.container.querySelector("[data-slot='card']")).toBeNull();
    expect(screen.container.querySelector(".tt-alternate-card")).toBeNull();
  });
});
