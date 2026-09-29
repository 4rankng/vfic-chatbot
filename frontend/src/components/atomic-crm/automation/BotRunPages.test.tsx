import { type ReactNode } from "react";
import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BotRun, BotRunTraceDetail } from "../types";

const mocks = vi.hoisted(() => ({
  redirect: vi.fn(),
  list: {
    data: [] as BotRun[],
    isPending: false,
    total: 0,
    page: 1,
    perPage: 25,
    setPage: () => {},
    setPerPage: () => {},
    hasNextPage: false,
    hasPreviousPage: false,
  },
}));

// `useTranslate` comes from the Vietnamese catalog. The list context (including
// the pagination half the kit's pager reads) is stubbed so the assertions below
// are about the page, not about react-admin's controller.
vi.mock("ra-core", () => ({
  ListBase: ({ children }: { children: ReactNode }) => children,
  // The kit's index re-exports the form controls, so their hooks have to exist
  // even though this page renders none of them.
  useInput: () => ({}),
  useDataProvider: () => ({}),
  useGetIdentity: () => ({ identity: { id: "admin-1" } }),
  useListContext: () => mocks.list,
  useListPaginationContext: () => mocks.list,
  useRedirect: () => mocks.redirect,
  useTranslate: () => testI18nProvider.translate,
}));

import { BotRunListContent } from "./BotRunList";
import { BotRunShowContent } from "./BotRunShow";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

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
    mocks.list.data = [run];
    mocks.list.isPending = false;
    mocks.list.total = 1;
  });

  it("keeps the list flat, concise and inside the shared scroll owner", async () => {
    const screen = await render(<BotRunListContent />);
    const row = screen.getByRole("button", {
      name: /Xem lần chạy #42: Đã gửi/,
    });
    const section = screen.getByRole("region", { name: "Nhật ký xử lý" });

    await expect.element(row).toBeVisible();
    await expect.element(screen.getByText("#42")).toBeVisible();
    const outcome = row
      .element()
      .querySelector<HTMLElement>("[data-slot='bot-run-outcome']");
    const rowText = row.element().textContent ?? "";

    expect(outcome).not.toBeNull();
    expect(rowText.indexOf("Đây là câu trả lời dài")).toBeLessThan(
      rowText.indexOf("Đã gửi"),
    );
    expect(row.element().getAttribute("aria-label")).not.toContain(
      "Đây là câu trả lời dài",
    );
    expect(section.element().querySelector(".overflow-y-auto")).toBeNull();

    // Tailkit a-c-timeline-01 rail: one marker per run, so the log reads
    // chronologically and by outcome instead of as a bare list.
    const items = section.element().querySelectorAll('[role="listitem"]');
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.firstElementChild?.tagName).toBe("SPAN");
    }

    await row.click();
    expect(mocks.redirect).toHaveBeenCalledWith("show", "bot_runs", 42);
  });

  it("pages the audit trail with the kit pager", async () => {
    const screen = await render(<BotRunListContent />);

    await expect
      .element(screen.getByRole("button", { name: "Trang tiếp" }))
      .toBeVisible();
    expect(screen.container.textContent).toContain("1-1 / 1");
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
    await expect.element(screen.getByText("Đã gửi")).toBeVisible();
    await expect
      .element(screen.getByRole("heading", { name: "Dấu vết quyết định" }))
      .toBeVisible();
    await expect
      .element(screen.getByText("Đã kiểm tra dữ liệu trước khi trả lời."))
      .not.toBeVisible();
    await screen
      .getByLabelText(/^Chi tiết lượt suy luận 1: .*minimax.*MiniMax-M2\.7$/)
      .click();
    await expect
      .element(screen.getByText("Đã kiểm tra dữ liệu trước khi trả lời."))
      .toBeVisible();
    expect(screen.container.querySelector("[data-slot='card']")).toBeNull();
  });
});
