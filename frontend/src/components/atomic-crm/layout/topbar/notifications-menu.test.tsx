import { MemoryRouter } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TestMessages } from "../../providers/commons/TestMessages";

const { mockUseNeedsAttention } = vi.hoisted(() => ({
  mockUseNeedsAttention: vi.fn(),
}));

vi.mock("./useNeedsAttention", () => ({
  useNeedsAttention: mockUseNeedsAttention,
}));

import { NotificationsMenu } from "./notifications-menu";

/**
 * The panel only mounts while it is open, so every test opens it through the
 * bell — the same interaction a recruiter performs.
 */
const renderMenu = (count: number) =>
  render(
    <TestMessages>
      <MemoryRouter>
        <NotificationsMenu count={count} />
      </MemoryRouter>
    </TestMessages>,
  );

const openMenu = async (count: number) => {
  const screen = await renderMenu(count);
  const trigger = page.getByRole("button", {
    name: `${count} cuộc trò chuyện cần chú ý`,
    exact: true,
  });
  await expect.element(trigger).toBeVisible();
  await trigger.click();

  const panel = page.getByRole("dialog", { name: "Thông báo", exact: true });
  await expect.element(panel).toBeVisible();

  return screen;
};

const sampleRows = [
  {
    id: "conv-1",
    last_inbound_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    contact: { display_name: "Nguyễn Văn An" },
    channel_identity: { provider: "zalo_oa" },
  },
  {
    id: "conv-2",
    last_inbound_at: new Date(Date.now() - 2 * 60 * 60_000).toISOString(),
    contact: { display_name: "  Trần Thị Bích  " },
    channel_identity: { provider: "facebook_messenger" },
  },
  {
    id: "conv-3",
    last_inbound_at: null,
    contact: null,
    channel_identity: { provider: "carrier_pigeon" },
  },
];

const needsAttention = (
  rows: unknown[],
  overrides: Partial<{
    total: number;
    isLoading: boolean;
    isError: boolean;
    refetch: () => void;
  }> = {},
) =>
  mockUseNeedsAttention.mockReturnValue({
    rows,
    total: rows.length,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  });

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
});

describe("NotificationsMenu", () => {
  it("lists each waiting conversation with its candidate, channel and deep link", async () => {
    needsAttention(sampleRows);
    await openMenu(sampleRows.length);

    const rows: readonly (readonly [RegExp, string])[] = [
      [/Nguyễn Văn An/, "/conversations?id=conv-1"],
      [/Trần Thị Bích/, "/conversations?id=conv-2"],
      // No contact at all: the anonymous fallback keeps the row actionable.
      [/Ứng viên ẩn danh/, "/conversations?id=conv-3"],
    ];

    for (const [name, href] of rows) {
      const link = page.getByRole("link", { name });
      await expect.element(link).toBeVisible();
      expect(link.element().getAttribute("href")).toBe(href);
    }

    // Provider ids are raw API strings: zalo_oa / facebook_messenger / unknown.
    for (const label of ["Zalo OA", "Messenger", "Kênh khác"]) {
      await expect
        .element(page.getByText(label, { exact: true }))
        .toBeVisible();
    }

    const seeAll = page.getByRole("link", { name: "Xem tất cả trong Hộp thư" });
    expect(seeAll.element().getAttribute("href")).toBe(
      "/conversations?needs_attention=true",
    );
  });

  it("shows the empty state when nothing is waiting", async () => {
    needsAttention([], { total: 0 });
    await renderMenu(0);

    const trigger = page.getByRole("button", {
      name: "Không có thông báo mới",
      exact: true,
    });
    await expect.element(trigger).toBeVisible();
    await trigger.click();

    await expect
      .element(page.getByText("Không có thông báo mới.", { exact: true }))
      .toBeVisible();
    expect(
      page.getByRole("link", { name: /Ứng viên|Nguyễn/ }).query(),
    ).toBeNull();
  });

  it("offers a retry that refetches when the rows fail to load", async () => {
    const refetch = vi.fn();
    needsAttention([], { total: 0, isError: true, refetch });

    await openMenu(2);

    await expect
      .element(page.getByText("Không tải được thông báo."))
      .toBeVisible();

    const retry = page.getByRole("button", { name: "Thử lại", exact: true });
    await expect.element(retry).toBeVisible();
    await retry.click();

    await expect.poll(() => refetch.mock.calls.length).toBe(1);
  });

  // The panel is a React Aria popover, so it mounts in a portal at the end of
  // the document — outside the topbar's `.uu-scope`. Unscoped, the library's
  // `bg-primary` resolves to the console's slate action fill and the whole
  // panel painted slate-on-slate (1.17:1).
  it("scopes the portal panel two trees away from the chrome", async () => {
    needsAttention(sampleRows);
    await openMenu(sampleRows.length);

    const panel = page.getByRole("dialog", { name: "Thông báo", exact: true });
    expect(panel.element().closest(".uu-scope")).not.toBeNull();
  });
});
