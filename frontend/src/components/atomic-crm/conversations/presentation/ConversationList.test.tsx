// FE-05 — regression coverage for the inbox row memo boundary.
//
// `ConversationList` used to build its rows by allocating
// `{...conversation, _presentation, _snippet}` inside a memo whose deps included
// the deferred search query and the read-id Set. Every rebuild therefore changed
// the identity of every row prop, so the memoized row could never skip: a
// deferred keystroke on a 25-row inbox rebuilt 25 objects, re-sorted and
// re-rendered 25 memoized components that all failed the shallow compare.
//
// These tests pin the fixed contract through the public `ConversationList`: a
// row re-renders only when its own conversation, presentation, snippet, read
// flag or active flag changes. Render counts are observed through the row's
// `LeadAvatar` child — the mock is deliberately not memoized and each row render
// creates a fresh `LeadAvatar` element, so React re-renders it exactly when the
// row body executes.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as RaCoreModule from "ra-core";
import { page } from "vitest/browser";
import { cleanup, render } from "vitest-browser-react";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router";
import type { ReactNode } from "react";

import type { Conversation } from "../../types";

// --- Mocks -------------------------------------------------------------

const avatarRenders = vi.hoisted(() => new Map<string, number>());
const listState = vi.hoisted(() => ({
  conversations: [] as Conversation[],
  isPending: false,
  error: null as Error | null,
}));
const emptySlots = vi.hoisted(() => ({}));
const viewportState = vi.hoisted(() => ({ isMobile: false }));

vi.mock("../LeadAvatar", () => ({
  LeadAvatar: ({ alt, children }: { alt?: string; children?: ReactNode }) => {
    const key = alt ?? "";
    avatarRenders.set(key, (avatarRenders.get(key) ?? 0) + 1);
    return <span data-testid="lead-avatar">{children}</span>;
  },
}));

vi.mock("ra-core", async (importOriginal) => ({
  // Spread the real module first: the kit barrel this component imports now
  // reaches `useInput`, and a hand-written mock that omits it breaks the whole
  // suite at import time rather than at an assertion.
  ...(await importOriginal<typeof RaCoreModule>()),
  // The component under test reads its labels from the Vietnamese catalog.
  useTranslate: () => testI18nProvider.translate,
  InfiniteListBase: ({ children }: { children?: ReactNode }) => <>{children}</>,
  useListContext: () => ({
    data: listState.conversations,
    isPending: listState.isPending,
    error: listState.error,
    refetch: () => Promise.resolve(),
  }),
  useInfinitePaginationContext: () => ({
    fetchNextPage: () => Promise.resolve(),
    hasNextPage: false,
    isFetchingNextPage: false,
  }),
  useGetOne: () => ({ data: undefined, isPending: false, isError: false }),
  RecordContextProvider: ({ children }: { children?: ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("../application/conversation-runtime", () => ({
  loadConversationSnippets: () => Promise.resolve({}),
}));

// Owned by another workstream; stubbed so this suite only exercises the list.
vi.mock("../ChannelAdapterSelector", () => ({
  ChannelAdapterSelector: () => <div data-testid="channel-adapter-selector" />,
}));

vi.mock("../useConversationCapabilitySlots", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    // No compiled row slot: rows fall back to the generic presentation.
    useConversationCapabilitySlots: () => emptySlots,
  };
});

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => viewportState.isMobile,
}));

// Keep the detail's public navigation callbacks and focusable Back control,
// without pulling its data, socket and dialog behavior into the list suite.
vi.mock("./ConversationShow", () => ({
  ConversationShowContent: ({
    onOpenList,
    onDeleted,
  }: {
    onOpenList?: () => void;
    onDeleted?: () => void;
  }) => (
    <section className="panel center-panel">
      <header className="chat-header conversation-header">
        <button
          className="conversation-header-back"
          onClick={onOpenList}
          aria-label="Mở danh sách hội thoại"
        >
          Quay lại
        </button>
        <button
          data-allow-tall
          className="conversation-header-identity conversation-header-identity-button"
        >
          Thông tin ứng viên
        </button>
      </header>
      <input aria-label="Trả lời" />
      <button onClick={onDeleted}>Xoá hội thoại</button>
    </section>
  ),
}));

import { ConversationList } from "./ConversationList";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

// --- Helpers -----------------------------------------------------------

const conversation = (
  id: string,
  displayName: string,
  lastInboundAt: string,
  patch: Partial<Conversation> = {},
): Conversation => ({
  id,
  zalo_chat_id: `zalo-${id}`,
  mode: "human",
  needs_human: false,
  assigned_recruiter_id: null,
  last_inbound_at: lastInboundAt,
  last_outbound_at: null,
  created_at: "2026-09-01T00:00:00.000Z",
  updated_at: lastInboundAt,
  unread_count: 0,
  contact: {
    id: `contact-${id}`,
    display_name: displayName,
    primary_phone: "0901234567",
    primary_email: null,
    avatar_url: null,
  },
  channel_identity: null,
  ...patch,
});

const rowNames = [
  "Ứng viên Một",
  "Ứng viên Hai",
  "Ứng viên Ba",
  "Trần Văn Khác",
];

// Four rows; the search term below ("Ứng viên") matches the first three only, so
// the keystroke test has an observable proof that the list did re-render.
const conversations = [
  conversation("conv-1", rowNames[0], "2026-09-01T04:00:00.000Z", {
    unread_count: 2,
  }),
  conversation("conv-2", rowNames[1], "2026-09-01T03:00:00.000Z"),
  conversation("conv-3", rowNames[2], "2026-09-01T02:00:00.000Z"),
  conversation("conv-4", rowNames[3], "2026-09-01T01:00:00.000Z"),
];

/** Row render count, observed through the row's `LeadAvatar` child. */
const rendersOf = (displayName: string) =>
  avatarRenders.get(`Ảnh đại diện của ${displayName}`) ?? 0;

const snapshotRowRenders = () =>
  new Map(rowNames.map((name) => [name, rendersOf(name)]));

const mountList = async () => {
  listState.conversations = conversations;
  const screen = await render(
    <MemoryRouter>
      <ConversationList />
    </MemoryRouter>,
  );
  // Desktop auto-selects the first row; wait for that to settle before taking a
  // render baseline.
  await expect
    .element(screen.getByRole("button", { name: /Ứng viên Một/ }))
    .toHaveAttribute("aria-current", "page");
  return screen;
};

beforeEach(async () => {
  // Desktop shell: the mobile layout (<= 767px) hides the list behind the open
  // detail pane, which would remove the rows from the accessibility tree.
  await page.viewport(1280, 720);
  viewportState.isMobile = false;
  avatarRenders.clear();
  listState.conversations = [];
  listState.isPending = false;
  listState.error = null;
});

describe("ConversationList — navigation focus", () => {
  const mountMobileList = async (initialEntries = ["/conversations"]) => {
    viewportState.isMobile = true;
    await page.viewport(390, 844);
    listState.conversations = conversations;
    const router = createMemoryRouter(
      [{ path: "/conversations", element: <ConversationList /> }],
      { initialEntries },
    );
    const screen = await render(<RouterProvider router={router} />);
    return { screen, router };
  };

  it("returns focus to the selected row after mobile Back", async () => {
    const { screen } = await mountMobileList();
    await screen.getByRole("button", { name: /Ứng viên Hai/ }).click();
    const identity = screen.getByRole("button", { name: "Thông tin ứng viên" });
    await expect.element(identity).toBeVisible();
    const detailPane = identity.element().closest(".center-panel")!;
    await expect.element(identity).toHaveFocus();
    await screen
      .getByRole("button", { name: "Mở danh sách hội thoại" })
      .click();

    await expect
      .element(screen.getByRole("button", { name: /Ứng viên Hai/ }))
      .toHaveFocus();
    // Reopening the same record reuses its existing pane. Let the visibility
    // transition finish to reproduce the settled mobile list seen in live QA.
    await vi.waitFor(() => {
      expect(getComputedStyle(detailPane).visibility).toBe("hidden");
    });
    await screen.getByRole("button", { name: /Ứng viên Hai/ }).click();
    await expect.element(identity).toHaveFocus();
  });

  it("returns focus to the selected row after browser Back", async () => {
    const { screen, router } = await mountMobileList();
    await screen.getByRole("button", { name: /Ứng viên Hai/ }).click();
    const back = screen.getByRole("button", {
      name: "Mở danh sách hội thoại",
    });
    await expect.element(back).toBeVisible();
    back.element().focus();
    await router.navigate(-1);

    await expect
      .element(screen.getByRole("button", { name: /Ứng viên Hai/ }))
      .toHaveFocus();
  });

  it("preserves deliberate reply focus while the mobile pane finishes opening", async () => {
    const { screen } = await mountMobileList();
    await screen.getByRole("button", { name: /Ứng viên Hai/ }).click();
    const reply = screen.getByRole("textbox", { name: "Trả lời" });
    await reply.click();
    const pane = reply.element().closest(".center-panel")!;
    await vi.waitFor(() => {
      expect(getComputedStyle(pane).transform).toBe("matrix(1, 0, 0, 1, 0, 0)");
    });

    await expect.element(reply).toHaveFocus();
  });

  it("focuses search when returning from a deep link outside the loaded list", async () => {
    const { screen } = await mountMobileList(["/conversations?id=conv-2"]);
    // Opening a fresh deep link is not an in-page pane transition and should
    // not steal the browser's initial focus.
    await expect
      .element(screen.getByRole("button", { name: "Thông tin ứng viên" }))
      .not.toHaveFocus();
    // Refresh removes the selected row before navigation. The list can still
    // render its other cached rows and search without waiting on detail data.
    listState.conversations = conversations.filter(({ id }) => id !== "conv-2");
    await screen
      .getByRole("button", { name: "Mở danh sách hội thoại" })
      .click();

    await expect.element(screen.getByLabelText("Tìm liên hệ")).toHaveFocus();
  });

  it("clears selection and focuses search after successful mobile deletion", async () => {
    const { screen } = await mountMobileList();
    await screen.getByRole("button", { name: /Ứng viên Hai/ }).click();
    // onDeleted runs before the server list refresh. Keep the deleted row in
    // this cached list to prove it cannot receive focus or retain selection.
    await screen.getByRole("button", { name: "Xoá hội thoại" }).click();

    await expect.element(screen.getByLabelText("Tìm liên hệ")).toHaveFocus();
    expect(
      screen.container.querySelector('.conversation[aria-current="page"]'),
    ).toBeNull();
  });

  it("keeps desktop focus while the selected conversation changes", async () => {
    listState.conversations = conversations;
    const router = createMemoryRouter([
      { path: "*", element: <ConversationList /> },
    ]);
    const screen = await render(<RouterProvider router={router} />);
    const search = screen.getByLabelText("Tìm liên hệ");
    await search.click();
    await router.navigate("/conversations?id=conv-2");

    await expect.element(search).toHaveFocus();
  });

  it("keeps a confirmed deleted row excluded through pending and failed desktop refresh", async () => {
    listState.conversations = [conversations[0]];
    const router = createMemoryRouter([
      { path: "*", element: <ConversationList /> },
    ]);
    const screen = await render(<RouterProvider router={router} />);
    await expect
      .element(screen.getByRole("button", { name: /Ứng viên Một/ }))
      .toHaveAttribute("aria-current", "page");
    await screen.getByRole("button", { name: "Xoá hội thoại" }).click();
    await expect
      .element(screen.getByRole("button", { name: /Ứng viên Một/ }))
      .not.toBeInTheDocument();

    // Loading/filter snapshots may temporarily contain no rows before the
    // failed refresh restores its stale data. Empty is not deletion proof.
    listState.conversations = [];
    listState.isPending = true;
    // This changes the InfiniteListBase key and remounts its content. Confirmed
    // deletion markers belong to the mounted inbox, above that filter boundary.
    await router.navigate("/conversations?needs_attention=true");

    // Context rerenders may keep the old record while refetch is pending, then
    // report an error. Neither may mount that deleted conversation's detail.
    for (const pending of [true, false]) {
      listState.conversations = [{ ...conversations[0] }];
      listState.isPending = pending;
      listState.error = pending ? null : new Error("Không thể tải hộp thư");
      await router.navigate("/conversations?needs_attention=true", {
        replace: true,
      });
      expect(
        screen.container.querySelector('.conversation[aria-current="page"]'),
      ).toBeNull();
      await expect
        .element(screen.getByRole("button", { name: "Thông tin ứng viên" }))
        .not.toBeInTheDocument();
    }

    listState.conversations = [conversations[1]];
    listState.error = null;
    await router.navigate("/conversations?needs_attention=true", {
      replace: true,
    });
    await expect
      .element(screen.getByRole("button", { name: /Ứng viên Hai/ }))
      .toHaveAttribute("aria-current", "page");
  });
});

afterEach(async () => {
  await cleanup();
});

// --- Tests -------------------------------------------------------------

describe("ConversationList — row memo boundary", () => {
  it("keeps every unchanged row from re-rendering while typing in search", async () => {
    const screen = await mountList();
    const before = snapshotRowRenders();

    await screen.getByLabelText("Tìm liên hệ").fill("Ứng viên");

    // Positive control: the deferred query did reach the list — the row that no
    // longer matches is gone, so the list (and its rows array) re-rendered.
    await vi.waitFor(() => {
      expect(screen.container.querySelectorAll(".conversation").length).toBe(3);
    });

    for (const name of rowNames) {
      expect(rendersOf(name)).toBe(before.get(name));
    }
  });

  it("keeps the other rows from re-rendering when one row is opened", async () => {
    const screen = await mountList();
    const before = snapshotRowRenders();
    expect(
      screen.container.querySelector('[aria-label="2 tin nhắn chưa đọc"]'),
    ).not.toBeNull();

    await screen.getByRole("button", { name: /Ứng viên Một/ }).click();

    // The click took effect: the optimistic read flag cleared the unread badge,
    // so that row's own props did change.
    await vi.waitFor(() => {
      expect(
        screen.container.querySelector('[aria-label="2 tin nhắn chưa đọc"]'),
      ).toBeNull();
    });

    // Positive control: the opened row re-rendered.
    expect(rendersOf(rowNames[0])).toBeGreaterThan(
      before.get(rowNames[0]) ?? 0,
    );
    // The read-id Set changed and the list re-sorted, but no other row's own
    // inputs did — so they must not have re-rendered.
    expect(rendersOf(rowNames[1])).toBe(before.get(rowNames[1]));
    expect(rendersOf(rowNames[2])).toBe(before.get(rowNames[2]));
    expect(rendersOf(rowNames[3])).toBe(before.get(rowNames[3]));
  });
});

describe("ConversationList — empty states", () => {
  it("renders the shared kit empty state when there is nothing to list", async () => {
    listState.conversations = [];
    const screen = await render(
      <MemoryRouter>
        <ConversationList />
      </MemoryRouter>,
    );

    await expect
      .element(screen.getByText("Chưa có cuộc trò chuyện"))
      .toBeVisible();
    const frame = screen.container.querySelector(".list-empty-state")!;
    // The empty state is the shared kit frame, not the bespoke icon stack the
    // list used to render: one status region carrying the directory's inset
    // class and no action button. The frame's own utility classes belong to
    // `kit/page-shell.test.tsx`; this lane does not emit the Tailwind layer, so
    // re-pinning them here would assert source text rather than behaviour.
    expect(frame.getAttribute("role")).toBe("status");
    // An inbox with no conversations has nothing to recover, so this variant
    // renders no action button.
    expect(frame.querySelector("button")).toBeNull();
  });

  it("clears the search from the filtered empty state's action", async () => {
    const screen = await mountList();
    await screen.getByLabelText("Tìm liên hệ").fill("không khớp ai");

    await expect
      .element(screen.getByText("Không tìm thấy hội thoại"))
      .toBeVisible();
    await screen
      .getByRole("button", { name: "Xoá tìm kiếm và bộ lọc" })
      .click();

    // The action slot is wired to the directory's own clear-and-reset handler,
    // so every row comes back.
    await vi.waitFor(() => {
      expect(screen.container.querySelectorAll(".conversation").length).toBe(4);
    });
  });
});
