import { MemoryRouter } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { mockUseNeedsAttention } = vi.hoisted(() => ({
  mockUseNeedsAttention: vi.fn(),
}));

vi.mock("./useNeedsAttention", () => ({
  useNeedsAttention: mockUseNeedsAttention,
}));

import { NotificationsPopover } from "./NotificationsPopover";

const sampleRows = [
  {
    id: "conv-1",
    last_inbound_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    contact: { display_name: "Nguyễn Văn An" },
    channel_identity: { provider: "zalo_bot" },
  },
  {
    id: "conv-2",
    last_inbound_at: new Date(Date.now() - 2 * 60 * 60_000).toISOString(),
    contact: { display_name: null },
    channel_identity: { provider: "facebook_messenger" },
  },
];

const renderPopover = (count = 2) =>
  render(
    <MemoryRouter>
      <NotificationsPopover count={count} />
    </MemoryRouter>,
  );

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
});

describe("NotificationsPopover", () => {
  it("renders the attention rows with names, channels, and deep-link destinations", async () => {
    mockUseNeedsAttention.mockReturnValue({
      rows: sampleRows,
      total: 2,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const screen = await renderPopover();

    await screen.getByRole("button", { name: "2 cuộc trò chuyện cần chú ý" }).click();

    const an = screen.getByRole("link", { name: /Nguyễn Văn An/ });
    await expect.element(an).toBeVisible();
    expect(an.element().getAttribute("href")).toBe("/conversations?id=conv-1");

    // Fallback name for a contact with no display_name.
    const anonymous = screen.getByRole("link", { name: /Ứng viên ẩn danh/ });
    expect(anonymous.element().getAttribute("href")).toBe("/conversations?id=conv-2");

    // Channel labels are surfaced.
    await expect.element(screen.getByText("Zalo Chatbot")).toBeVisible();
    await expect.element(screen.getByText("Messenger")).toBeVisible();

    // "See all" footer hands off to the inbox.
    const seeAll = screen.getByRole("link", { name: "Xem tất cả trong Hộp thư" });
    expect(seeAll.element().getAttribute("href")).toBe(
      "/conversations?needs_attention=true",
    );
  });

  it("shows the empty state when there is nothing to attend to", async () => {
    mockUseNeedsAttention.mockReturnValue({
      rows: [],
      total: 0,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const screen = await renderPopover(0);

    await screen
      .getByRole("button", { name: "Không có thông báo mới" })
      .click();
    await expect
      .element(screen.getByText("Không có thông báo mới."))
      .toBeVisible();
  });

  it("renders skeleton rows without crashing while loading", async () => {
    mockUseNeedsAttention.mockReturnValue({
      rows: [],
      total: 0,
      isLoading: true,
      isError: false,
      refetch: vi.fn(),
    });
    const screen = await renderPopover();

    await screen
      .getByRole("button", { name: "2 cuộc trò chuyện cần chú ý" })
      .click();
    // Three shimmering placeholder rows. Popover content is portalled to
    // document.body, so query the document rather than the test container.
    await expect
      .poll(() =>
        document.querySelectorAll(
          ".workspace-notifications-item--skeleton",
        ).length,
      )
      .toBe(3);
  });
});
