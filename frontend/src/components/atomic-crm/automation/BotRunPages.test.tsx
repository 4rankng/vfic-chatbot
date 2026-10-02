import { type ReactNode } from "react";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@/index.css";

import type { BotRun, BotRunDetail } from "../types";

const mocks = vi.hoisted(() => ({
  redirect: vi.fn(),
  notify: vi.fn(),
  list: {
    data: [] as BotRun[],
    isPending: false,
    isFetching: false,
    error: null as Error | null,
    refetch: vi.fn(),
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
  // The kit's ListTable wraps every cell in the record context, so the mock
  // has to provide the passthrough even though this page asserts no cells.
  RecordContextProvider: ({ children }: { children: ReactNode }) => children,
  // The kit's index re-exports the form controls, so their hooks have to exist
  // even though this page renders none of them.
  useInput: () => ({}),
  useDataProvider: () => ({}),
  useGetIdentity: () => ({ identity: { id: "admin-1" } }),
  useListContext: () => mocks.list,
  useListPaginationContext: () => mocks.list,
  useRedirect: () => mocks.redirect,
  useNotify: () => mocks.notify,
  useTranslate: () => testI18nProvider.translate,
}));

import { BotRunListContent } from "./BotRunList";
import { outcomeMeta } from "./botRunMeta";
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
  afterEach(async () => {
    await cleanup();
    await page.viewport(1280, 720);
  });
  beforeEach(() => {
    mocks.redirect.mockReset();
    mocks.notify.mockReset();
    mocks.list.data = [run];
    mocks.list.isPending = false;
    mocks.list.isFetching = false;
    mocks.list.error = null;
    mocks.list.refetch.mockReset();
    mocks.list.refetch.mockResolvedValue({ error: null });
    mocks.list.total = 1;
  });

  it("lets phone audit rows contain their preview and status without overlapping", async () => {
    await page.viewport(390, 844);
    mocks.list.data = [run, { ...run, id: 43 }];
    mocks.list.total = 2;
    const screen = await render(
      <div className="workspace-frame-content">
        <BotRunListContent />
      </div>,
    );
    const rows = screen.container.querySelectorAll<HTMLElement>(".bot-run-row");
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row.hasAttribute("data-allow-tall")).toBe(true);
      expect(row.getBoundingClientRect().height).toBeGreaterThanOrEqual(88);
      const preview = row.querySelector(".bot-run-preview")!;
      const status = row.querySelector('[data-slot="bot-run-outcome"]')!;
      expect(preview.getBoundingClientRect().bottom).toBeLessThanOrEqual(
        row.getBoundingClientRect().bottom,
      );
      expect(status.getBoundingClientRect().bottom).toBeLessThanOrEqual(
        row.getBoundingClientRect().bottom,
      );
    }
    expect(rows[1].getBoundingClientRect().top).toBeGreaterThanOrEqual(
      rows[0].getBoundingClientRect().bottom,
    );
  });

  it("distinguishes a failed initial request from an empty audit trail", async () => {
    mocks.list.data = [];
    mocks.list.error = new Error("request failed");
    const screen = await render(<BotRunListContent />);

    await expect.element(screen.getByRole("alert")).toBeVisible();
    await expect
      .element(screen.getByText("Chưa tải được nhật ký"))
      .toBeVisible();
    await expect
      .element(screen.getByText("Chưa có lần chạy bot nào"))
      .not.toBeInTheDocument();
    await screen.getByRole("button", { name: "Thử lại" }).click();
    expect(mocks.list.refetch).toHaveBeenCalledTimes(1);
  });

  it("keeps a successful empty response distinct from failure", async () => {
    mocks.list.data = [];
    const screen = await render(<BotRunListContent />);

    await expect
      .element(screen.getByText("Chưa có lần chạy bot nào"))
      .toBeVisible();
    await expect.element(screen.getByRole("alert")).not.toBeInTheDocument();
    await expect
      .element(screen.getByRole("button", { name: "Thử lại" }))
      .not.toBeInTheDocument();
  });

  it("marks the audit region busy during the first request", async () => {
    mocks.list.data = [];
    mocks.list.isPending = true;
    mocks.list.isFetching = true;
    const screen = await render(<BotRunListContent />);

    await expect
      .element(screen.getByRole("status", { name: "Đang tải" }))
      .toBeInTheDocument();
    await expect
      .element(screen.getByRole("region", { name: "Nhật ký xử lý" }))
      .toHaveAttribute("aria-busy", "true");
    await expect
      .element(screen.getByText("Chưa có lần chạy bot nào"))
      .not.toBeInTheDocument();
  });

  it("preserves known runs while a background request fails or retries", async () => {
    mocks.list.error = new Error("background request failed");
    let finishRetry!: (result: { error: null }) => void;
    mocks.list.refetch.mockReturnValueOnce(
      new Promise((resolve) => {
        finishRetry = resolve;
      }),
    );
    const screen = await render(<BotRunListContent />);
    const section = screen.getByRole("region", { name: "Nhật ký xử lý" });
    const row = screen.getByRole("button", { name: /Xem lần chạy #42:/ });
    const retry = screen.getByRole("button", { name: "Thử lại" });

    await expect.element(row).toBeVisible();
    await expect.element(screen.getByRole("alert")).toBeVisible();
    await expect
      .element(
        screen.getByText(
          "Chưa cập nhật được nhật ký. Dữ liệu đã tải vẫn được giữ lại.",
        ),
      )
      .toBeVisible();
    await retry.click();
    await expect.element(section).toHaveAttribute("aria-busy", "true");
    await expect.element(retry).toBeDisabled();
    await expect.element(row).toBeVisible();
    finishRetry({ error: null });
    await expect.element(section).toHaveAttribute("aria-busy", "false");
    await expect.element(retry).toBeEnabled();
  });

  it.each(["query result", "rejected promise"])(
    "announces a retry failure from %s",
    async (failure) => {
      mocks.list.data = [];
      mocks.list.error = new Error("request failed");
      if (failure === "query result") {
        mocks.list.refetch.mockResolvedValueOnce({
          error: new Error("private provider error"),
        });
      } else {
        mocks.list.refetch.mockRejectedValueOnce(
          new Error("private provider error"),
        );
      }
      const screen = await render(<BotRunListContent />);

      await screen.getByRole("button", { name: "Thử lại" }).click();
      await expect
        .poll(() => mocks.notify.mock.calls)
        .toEqual([
          ["Vẫn chưa tải được nhật ký. Vui lòng thử lại.", { type: "error" }],
        ]);
      await expect.element(screen.getByRole("alert")).toBeVisible();
      await expect
        .element(screen.getByRole("region", { name: "Nhật ký xử lý" }))
        .toHaveAttribute("aria-busy", "false");
      expect(screen.container.textContent).not.toContain(
        "private provider error",
      );
    },
  );

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

  it("shows run facts without nested cards", async () => {
    const detail: BotRunDetail = {
      id: 42,
      conversation_id: "conversation-42",
      started_at: "2026-07-23T10:00:00Z",
      ended_at: "2026-07-23T10:00:02Z",
      outcome: "sent",
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
    expect(screen.container.querySelector("[data-slot='card']")).toBeNull();
  });

  // A `-foreground` token is the ink for text sitting ON a filled warning
  // surface. The outcome marker paints itself and its label with `currentColor`
  // straight onto the cream card, so a `-foreground` token there is white on
  // cream and the suppressed run simply vanished. Every outcome owes a plain ink.
  it("gives every outcome an ink, never a filled-surface foreground", async () => {
    for (const outcome of ["sent", "suppressed", "error"] as const) {
      const indicator = outcomeMeta(outcome).indicatorClasses;
      expect(indicator, outcome).toMatch(/^text-/);
      expect(indicator, outcome).not.toMatch(/-foreground$/);
    }

    mocks.list.data = [{ ...run, outcome: "suppressed" }];
    const screen = await render(<BotRunListContent />);
    const marker = screen.container.querySelector<HTMLElement>(
      "[data-slot='bot-run-outcome']",
    );

    expect(marker).not.toBeNull();
    expect(marker!.textContent).toBe("Không gửi được");
    expect(getComputedStyle(marker!).color).not.toBe("rgb(255, 255, 255)");
  });
});
