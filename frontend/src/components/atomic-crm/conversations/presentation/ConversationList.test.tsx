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
import { page } from "vitest/browser";
import { cleanup, render } from "vitest-browser-react";
import { MemoryRouter } from "react-router";
import type { ReactNode } from "react";

import type { Conversation } from "../../types";

// --- Mocks -------------------------------------------------------------

const avatarRenders = vi.hoisted(() => new Map<string, number>());
const listState = vi.hoisted(() => ({ conversations: [] as Conversation[] }));
const emptySlots = vi.hoisted(() => ({}));

vi.mock("../LeadAvatar", () => ({
  LeadAvatar: ({ alt, children }: { alt?: string; children?: ReactNode }) => {
    const key = alt ?? "";
    avatarRenders.set(key, (avatarRenders.get(key) ?? 0) + 1);
    return <span data-testid="lead-avatar">{children}</span>;
  },
}));

vi.mock("ra-core", () => ({
  InfiniteListBase: ({ children }: { children?: ReactNode }) => <>{children}</>,
  useListContext: () => ({
    data: listState.conversations,
    isPending: false,
    error: null,
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

vi.mock("../conversation-capability", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    // No compiled row slot: rows fall back to the generic presentation.
    useConversationCapabilitySlots: () => emptySlots,
  };
});

// Desktop: the panel stays visible once a conversation is open (the mobile
// shell hides the list behind the detail pane).
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => false }));

vi.mock("./ConversationShow", () => ({ ConversationShowContent: () => null }));

import { ConversationList } from "./ConversationList";

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
  avatarRenders.clear();
  listState.conversations = [];
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
    expect(rendersOf(rowNames[0])).toBeGreaterThan(before.get(rowNames[0]) ?? 0);
    // The read-id Set changed and the list re-sorted, but no other row's own
    // inputs did — so they must not have re-rendered.
    expect(rendersOf(rowNames[1])).toBe(before.get(rowNames[1]));
    expect(rendersOf(rowNames[2])).toBe(before.get(rowNames[2]));
    expect(rendersOf(rowNames[3])).toBe(before.get(rowNames[3]));
  });
});
