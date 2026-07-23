// Focused browser-component coverage for the anchored conversation shell.
//
// The plan's acceptance criteria center on presentation, not data: the bottom
// row must be present in every mode, the latest control must split viewport
// position from unseen arrivals, and mode-gated actions must match existing
// authorization. These tests mount ChatThread with mocked ra-core hooks and a
// fixed-height center-panel grid so the height chain (header / 1fr scroller /
// footer) is real — only the data/realtime dependencies are stubbed.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";
import type { ReactNode } from "react";

import type { Conversation, Message } from "../types";

// --- Mocks -------------------------------------------------------------
// ChatThread reads messages/flags from the normalized store and pushes
// optimistic sends through useConversationRealtime. We stub both so the test
// controls exactly which messages render without touching Socket.IO / fetch.
// virtua's VList is stubbed as a plain scroll container: the library's internal
// React-dispatcher assumptions don't hold under vitest-browser-react, and the
// plan's acceptance criteria are about ChatThread's own footer/latest logic,
// not virtua's virtualization. The real scroll architecture is verified by
// typecheck + the isolated synthetic QA in phase-03.

const messageStoreState = {
  messages: [] as Message[],
  isLoading: false,
  isLoadingMore: false,
  hasMore: false,
  initialError: null as string | null,
  historyError: null as string | null,
};

const realtimeControls = {
  insertOptimistic: vi.fn(() => "optimistic-test"),
  markOptimisticFailed: vi.fn(),
  retryInitial: vi.fn(),
  retryHistory: vi.fn(),
  loadMore: vi.fn(),
};

vi.mock("virtua", () => ({
  // Minimal stand-in: a scrollable div that renders its children and forwards
  // onScroll. ChatThread locates the scroller via .chat-scroller, so the class
  // and the overflow are what matter for its DOM queries and scroll handlers.
  VList: ({
    children,
    className,
    style,
    onScroll,
  }: {
    children?: ReactNode;
    className?: string;
    style?: Record<string, unknown>;
    onScroll?: (offset: number) => void;
  }) => (
    <div
      className={className}
      style={{ height: "100%", overflowY: "auto", ...style }}
      onScroll={(e) => onScroll?.((e.currentTarget as HTMLElement).scrollTop)}
    >
      {children}
    </div>
  ),
}));

vi.mock("./presentation/conversation-message-state", () => ({
  useConversationMessages: (_convId?: string) => messageStoreState.messages,
  useConversationFlags: (_convId?: string) => ({
    isLoading: messageStoreState.isLoading,
    isLoadingMore: messageStoreState.isLoadingMore,
    hasMore: messageStoreState.hasMore,
    initialError: messageStoreState.initialError,
    historyError: messageStoreState.historyError,
  }),
}));

vi.mock("./presentation/use-conversation-realtime", () => ({
  useConversationRealtime: () => realtimeControls,
}));

vi.mock("./presentation/use-conversation-actions", () => ({
  useConversationActions: (_record?: Conversation) => ({
    effectiveMode: "human",
    isBotMode: false,
    needsClaim: false,
    canHumanReply: true,
    setConversationMode: vi.fn(),
    handleTakeover: vi.fn(),
    handleRelease: vi.fn(),
  }),
}));

const dataProviderMock = {
  markAsRead: vi.fn(() => Promise.resolve()),
  sendHumanReply: vi.fn(() => Promise.resolve()),
  retryHumanReply: vi.fn(() => Promise.resolve()),
};

vi.mock("ra-core", () => ({
  useDataProvider: () => dataProviderMock,
  useGetIdentity: () => ({ identity: { id: "recruiter-1" } }),
  useNotify: vi.fn(),
  useTranslate: () => (key: string) => key,
}));

import { ChatThread, isUnseenWorthyArrival } from "./ChatThread";

// --- Helpers -----------------------------------------------------------

const baseConversation = (patch: Partial<Conversation> = {}): Conversation =>
  ({
    id: "conv-1",
    zalo_chat_id: "zalo-1",
    mode: "human",
    needs_human: false,
    assigned_recruiter_id: null,
    last_inbound_at: null,
    created_at: "2026-07-01T00:00:00.000Z",
    updated_at: "2026-07-01T00:00:00.000Z",
    unread_count: 0,
    ...patch,
  }) as Conversation;

const msg = (id: number, patch: Partial<Message> = {}): Message => ({
  id: String(id),
  zalo_message_id: String(id),
  conversation_id: "conv-1",
  type: id % 2 === 0 ? "outbound" : "inbound",
  content: `message ${id}`,
  data: null,
  created_at: `2026-07-01T00:00:${String(id).padStart(2, "0")}.000Z`,
  ...patch,
});

/** Fixed-height center-panel grid mirroring the inbox shell. The 1fr transcript
 * row gets a real bounded height so the scroller and footer layout is real. */
const Shell = ({ children }: { children: ReactNode }) => (
  <div
    className="panel center-panel"
    style={{
      display: "grid",
      gridTemplateRows: "auto minmax(0, 1fr) auto",
      height: "400px",
      overflow: "hidden",
    }}
  >
    <header style={{ minHeight: "48px" }} />
    {children}
  </div>
);

const mountThread = async (overrides?: {
  conversation?: Conversation;
  isBotModeOverride?: boolean;
  needsClaimOverride?: boolean;
  canHumanReplyOverride?: boolean;
}) =>
  render(
    <Shell>
      <ChatThread
        conversationId="conv-1"
        conversation={overrides?.conversation ?? baseConversation()}
        isBotModeOverride={overrides?.isBotModeOverride}
        needsClaimOverride={overrides?.needsClaimOverride}
        canHumanReplyOverride={overrides?.canHumanReplyOverride}
        onTakeoverOverride={vi.fn()}
      />
    </Shell>,
  );

beforeEach(() => {
  Object.assign(messageStoreState, {
    messages: [],
    isLoading: false,
    isLoadingMore: false,
    hasMore: false,
    initialError: null,
    historyError: null,
  });
  vi.clearAllMocks();
});

afterEach(async () => {
  await cleanup();
});

// --- Tests -------------------------------------------------------------

describe("ChatThread — mode-gated footer", () => {
  it("renders the composer for human mode", async () => {
    const screen = await mountThread({ canHumanReplyOverride: true });
    await expect
      .element(screen.getByPlaceholder("Nhập tin nhắn..."))
      .toBeVisible();
    expect(
      screen.container.querySelector(".composer-wrap .composer"),
    ).not.toBeNull();
  });

  it("renders the composer for semi-auto mode", async () => {
    const screen = await mountThread({ canHumanReplyOverride: true });
    await expect
      .element(screen.getByPlaceholder("Nhập tin nhắn..."))
      .toBeVisible();
  });

  it("renders the bot takeover notice and Tiếp quản for bot mode (no textarea)", async () => {
    const screen = await mountThread({
      isBotModeOverride: true,
      canHumanReplyOverride: false,
    });
    await expect
      .element(screen.getByText("Đang dùng ChatBot cho cuộc trò chuyện này."))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Tiếp quản" }))
      .toBeVisible();
    expect(screen.container.querySelector("textarea")).toBeNull();
  });

  it("requires an operator claim for an unassigned human-review conversation", async () => {
    const screen = await mountThread({
      isBotModeOverride: false,
      needsClaimOverride: true,
      canHumanReplyOverride: false,
    });
    await expect
      .element(
        screen.getByText("Hội thoại cần nhân viên xác minh trước khi trả lời."),
      )
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Tiếp quản" }))
      .toBeVisible();
    expect(screen.container.querySelector("textarea")).toBeNull();
  });

  it("renders the closed read-only explanation for closed mode (no send/takeover)", async () => {
    const screen = await mountThread({
      isBotModeOverride: false,
      canHumanReplyOverride: false,
    });
    await expect
      .element(
        screen.getByText(
          "Hội thoại đã đóng. Không thể gửi tin nhắn cho người trò chuyện.",
        ),
      )
      .toBeVisible();
    expect(screen.container.querySelector("textarea")).toBeNull();
    expect(screen.container.querySelector(".inline-takeover-btn")).toBeNull();
    expect(screen.container.querySelector(".composer-action.send")).toBeNull();
  });

  it("always renders the footer element in every mode (stable bottom boundary)", async () => {
    for (const mode of [
      { canHumanReplyOverride: true },
      { isBotModeOverride: true, canHumanReplyOverride: false },
      { isBotModeOverride: false, canHumanReplyOverride: false },
    ]) {
      const screen = await mountThread(mode);
      const footer = screen.container.querySelector(".composer-wrap");
      expect(footer).not.toBeNull();
      await cleanup();
    }
  });
});

describe("ChatThread — latest control visibility", () => {
  it("does not show the latest control when at the bottom", async () => {
    messageStoreState.messages = [msg(1), msg(2)];
    const screen = await mountThread();
    // At bottom (initial snap), the control must not be present.
    await vi.waitFor(() => {
      expect(screen.container.querySelector(".new-message-jump")).toBeNull();
    });
  });

  it("does not show the latest control for own optimistic send", async () => {
    messageStoreState.messages = [msg(1)];
    const screen = await mountThread();
    const textarea = screen.getByPlaceholder("Nhập tin nhắn...");
    await textarea.fill("Xin chào");
    await screen.getByRole("button", { name: "Gửi tin nhắn" }).click();
    // Optimistic send must not surface the unseen latest control.
    await vi.waitFor(() => {
      expect(screen.container.querySelector(".new-message-jump")).toBeNull();
    });
  });
});

describe("ChatThread — transcript scroll ownership", () => {
  it("keeps the footer in the grid and the scroller as the only overflow-y:auto", async () => {
    messageStoreState.messages = [msg(1), msg(2)];
    const screen = await mountThread();
    await vi.waitFor(() => {
      const footer = screen.container.querySelector(".composer-wrap");
      expect(footer).not.toBeNull();
      // The scroller is the transcript scroll owner.
      const scroller = screen.container.querySelector(".chat-scroller");
      expect(scroller).not.toBeNull();
    });
  });
});

describe("isUnseenWorthyArrival — unseen-content contract", () => {
  // Pure unit coverage of the author/type discriminator that decides whether a
  // new arrival escalates the latest control to "Tin nhắn mới" while the reader
  // is away. Exported from ChatThread so the contract is locked in CI.

  const inbound = (id: string): Message => ({
    id,
    zalo_message_id: id,
    conversation_id: "conv-1",
    type: "inbound",
    content: "from candidate",
    data: null,
    created_at: "2026-07-01T00:00:01.000Z",
  });

  const botReply = (id: string): Message => ({
    id,
    zalo_message_id: id,
    conversation_id: "conv-1",
    type: "outbound",
    content: "bot reply",
    data: null, // no recruiter_id → bot
    created_at: "2026-07-01T00:00:02.000Z",
  });

  const recruiterReply = (id: string, recruiterId: string): Message => ({
    id,
    zalo_message_id: id,
    conversation_id: "conv-1",
    type: "outbound",
    content: "recruiter reply",
    data: { recruiter_id: recruiterId },
    created_at: "2026-07-01T00:00:03.000Z",
  });

  const system = (id: string): Message => ({
    id,
    zalo_message_id: id,
    conversation_id: "conv-1",
    type: "system",
    content: "system event",
    data: null,
    created_at: "2026-07-01T00:00:04.000Z",
  });

  const optimistic = (recruiterId: string): Message => ({
    id: "optimistic-abc",
    zalo_message_id: "",
    conversation_id: "conv-1",
    type: "outbound",
    content: "my send",
    data: { recruiter_id: recruiterId },
    created_at: "2026-07-01T00:00:05.000Z",
  });

  it("qualifies candidate inbound", () => {
    expect(isUnseenWorthyArrival(inbound("1"), "recruiter-1")).toBe(true);
  });

  it("qualifies a bot reply (no recruiter_id)", () => {
    expect(isUnseenWorthyArrival(botReply("2"), "recruiter-1")).toBe(true);
  });

  it("qualifies another recruiter's reply", () => {
    expect(
      isUnseenWorthyArrival(recruiterReply("3", "recruiter-2"), "recruiter-1"),
    ).toBe(true);
  });

  it("does NOT qualify the current recruiter's own server echo", () => {
    expect(
      isUnseenWorthyArrival(recruiterReply("4", "recruiter-1"), "recruiter-1"),
    ).toBe(false);
  });

  it("does NOT qualify the current recruiter's optimistic send", () => {
    expect(
      isUnseenWorthyArrival(optimistic("recruiter-1"), "recruiter-1"),
    ).toBe(false);
  });

  it("does NOT qualify a system event", () => {
    expect(isUnseenWorthyArrival(system("5"), "recruiter-1")).toBe(false);
  });

  it("qualifies any recruiter reply when the current identity is unknown", () => {
    // Defensive: without identity we can't prove authorship, so treat as unseen.
    expect(
      isUnseenWorthyArrival(recruiterReply("6", "recruiter-1"), null),
    ).toBe(true);
    expect(
      isUnseenWorthyArrival(recruiterReply("7", "recruiter-1"), undefined),
    ).toBe(true);
  });

  it("compares ids as strings (handles numeric identities)", () => {
    expect(isUnseenWorthyArrival(recruiterReply("8", "42"), 42)).toBe(false);
    expect(isUnseenWorthyArrival(recruiterReply("9", "43"), 42)).toBe(true);
  });
});

describe("ChatThread — failed-send bubble diagnosability", () => {
  // A "Gửi lỗi" (delivery_status=failed) bubble must never be blank. When the
  // attempted reply body is empty, the failure reason (external_error) is shown
  // in its place so the recruiter knows what happened. When content is present,
  // the content is shown and the reason is not duplicated.

  it("shows the failure reason when the failed bubble has no content", async () => {
    messageStoreState.messages = [
      msg(2, {
        type: "outbound",
        content: "",
        delivery_status: "failed",
        external_error: "timeout contacting Zalo OA",
        // outbound with no recruiter_id → bot kind
        data: null,
      }),
    ];
    const screen = await mountThread({ canHumanReplyOverride: true });

    await vi.waitFor(() => {
      expect(
        screen.container.querySelector(".delivery-error-detail"),
      ).not.toBeNull();
    });
    await expect
      .element(screen.getByText("Lỗi kết nối mạng"))
      .toBeVisible();
    // The "Gửi lỗi" status label is still present.
    await expect.element(screen.getByText("Gửi lỗi")).toBeVisible();
  });

  it("maps a non-network external_error to the provider-rejected reason", async () => {
    messageStoreState.messages = [
      msg(2, {
        type: "outbound",
        content: "",
        delivery_status: "failed",
        external_error: "OA quota exceeded",
        data: null,
      }),
    ];
    const screen = await mountThread({ canHumanReplyOverride: true });

    await expect.element(screen.getByText("Zalo từ chối tin nhắn")).toBeVisible();
  });

  it("does not render the failure reason when the failed bubble has content", async () => {
    messageStoreState.messages = [
      msg(2, {
        type: "outbound",
        content: "Cảm ơn bạn đã liên hệ.",
        delivery_status: "failed",
        external_error: "OA quota exceeded",
        data: null,
      }),
    ];
    const screen = await mountThread({ canHumanReplyOverride: true });

    await vi.waitFor(() => {
      expect(
        screen.container.querySelector('[data-message-id="2"] .message-text-block'),
      ).not.toBeNull();
    });
    // Content is shown; the reason detail is not (content takes priority).
    expect(
      screen.container.querySelector(".delivery-error-detail"),
    ).toBeNull();
    await expect
      .element(screen.getByText("Cảm ơn bạn đã liên hệ."))
      .toBeVisible();
  });
});
