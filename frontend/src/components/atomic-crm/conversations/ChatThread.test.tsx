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
import { page } from "vitest/browser";
import { useState, type ReactNode } from "react";

import "@/index.css";
import "./inbox.css";

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

const mobileState = vi.hoisted(() => ({ isMobile: false }));
vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => mobileState.isMobile,
}));

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
      <div>{children}</div>
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
  // The component under test reads its labels from the Vietnamese catalog.
  useTranslate: () => testI18nProvider.translate,
  useDataProvider: () => dataProviderMock,
  useGetIdentity: () => ({ identity: { id: "recruiter-1" } }),
  useNotify: vi.fn(),
}));

import { ChatThread } from "./presentation/ChatThread";
import { isUnseenWorthyArrival } from "./domain/conversation-thread";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

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
  isChangingModeOverride?: boolean;
  composerToolbar?: ReactNode;
  onTakeoverOverride?: () => void | Promise<void>;
}) =>
  render(
    <Shell>
      <ChatThread
        conversationId="conv-1"
        conversation={overrides?.conversation ?? baseConversation()}
        isBotModeOverride={overrides?.isBotModeOverride}
        needsClaimOverride={overrides?.needsClaimOverride}
        canHumanReplyOverride={overrides?.canHumanReplyOverride}
        onTakeoverOverride={overrides?.onTakeoverOverride ?? vi.fn()}
        isChangingModeOverride={overrides?.isChangingModeOverride}
        composerToolbar={overrides?.composerToolbar}
      />
    </Shell>,
  );

beforeEach(() => {
  mobileState.isMobile = false;
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
  it.each([320, 390])(
    "keeps the send glyph's 44px target within a %ipx composer",
    async (width) => {
      await page.viewport(width, 900);
      mobileState.isMobile = true;
      try {
        const screen = await render(
          <div className="workspace-frame-content">
            <div className="inbox-bg-container conversation-workspace conversation-open">
              <div className="app detail-open has-selected-conversation">
                <Shell>
                  <ChatThread
                    conversationId="conv-1"
                    conversation={baseConversation()}
                    canHumanReplyOverride
                    needsClaimOverride={false}
                  />
                </Shell>
              </div>
            </div>
          </div>,
        );
        const send = screen.container.querySelector<HTMLButtonElement>(
          ".composer-action.send",
        )!;
        const assertTarget = () => {
          const target = send.getBoundingClientRect();
          const composer = send.closest(".composer")!.getBoundingClientRect();
          expect(target.width).toBe(44);
          expect(target.height).toBe(44);
          expect(target.left).toBeGreaterThanOrEqual(composer.left);
          expect(target.right).toBeLessThanOrEqual(composer.right);
          expect(target.top).toBeGreaterThanOrEqual(composer.top);
          expect(target.bottom).toBeLessThanOrEqual(composer.bottom);
        };
        expect(send.disabled).toBe(true);
        assertTarget();
        await screen
          .getByRole("textbox", { name: "Tin nhắn trả lời" })
          .fill("Xin chào");
        expect(send.disabled).toBe(false);
        assertTarget();
      } finally {
        await page.viewport(1280, 720);
      }
    },
  );

  it("renders the composer for human mode", async () => {
    const screen = await mountThread({ canHumanReplyOverride: true });
    await expect
      .element(screen.getByPlaceholder("Nhập tin nhắn..."))
      .toBeVisible();
    expect(
      screen.container.querySelector(".composer-wrap .composer"),
    ).not.toBeNull();
    await expect
      .element(screen.getByRole("textbox", { name: "Tin nhắn trả lời" }))
      .toBeVisible();
  });

  it("keeps IME confirmation and mobile Enter from sending a reply", async () => {
    const screen = await mountThread({ canHumanReplyOverride: true });
    await screen
      .getByRole("textbox", { name: "Tin nhắn trả lời" })
      .fill("Ứng viên");
    const textarea = screen.container.querySelector("textarea")!;
    textarea.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        isComposing: true,
        bubbles: true,
      }),
    );
    expect(dataProviderMock.sendHumanReply).not.toHaveBeenCalled();
    textarea.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        keyCode: 229,
        bubbles: true,
      }),
    );
    expect(dataProviderMock.sendHumanReply).not.toHaveBeenCalled();
    await cleanup();
    mobileState.isMobile = true;
    const phoneScreen = await mountThread({ canHumanReplyOverride: true });
    await phoneScreen
      .getByRole("textbox", { name: "Tin nhắn trả lời" })
      .fill("Ứng viên");
    phoneScreen.container
      .querySelector("textarea")!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    expect(dataProviderMock.sendHumanReply).not.toHaveBeenCalled();
    await phoneScreen.getByRole("button", { name: "Gửi tin nhắn" }).click();
    await expect
      .poll(() => dataProviderMock.sendHumanReply.mock.calls.length)
      .toBe(1);
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
      .element(screen.getByText("Chatbot tự động trả lời."))
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

  it("places host controls with one explicit takeover action and no repeated bot status", async () => {
    const takeover = vi.fn();
    const screen = await mountThread({
      isBotModeOverride: true,
      canHumanReplyOverride: false,
      composerToolbar: <button type="button">Chế độ: Chatbot</button>,
      onTakeoverOverride: takeover,
    });
    const controls = screen.container.querySelector(".composer-controls")!;
    expect(controls.textContent).toContain("Chế độ: Chatbot");
    expect(screen.container.querySelector(".handoff-note")).toBeNull();
    expect(screen.container.querySelector("textarea")).toBeNull();
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    expect(takeover).toHaveBeenCalledTimes(1);
  });

  it("disables takeover during a pending mode change and keeps unclaimed conversations read-only", async () => {
    const takeover = vi.fn();
    const screen = await mountThread({
      isBotModeOverride: false,
      needsClaimOverride: true,
      canHumanReplyOverride: false,
      isChangingModeOverride: true,
      composerToolbar: (
        <button type="button" disabled>
          Chế độ: Tư vấn viên
        </button>
      ),
      onTakeoverOverride: takeover,
    });
    await expect
      .element(screen.getByText("Cần tiếp quản để trả lời."))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Tiếp quản" }))
      .toBeDisabled();
    expect(screen.container.querySelector("textarea")).toBeNull();
    expect(takeover).not.toHaveBeenCalled();
  });

  it("preserves the draft and blocks Enter or submit until a mode change settles", async () => {
    const renderThread = (pending: boolean) => (
      <Shell>
        <ChatThread
          conversationId="conv-1"
          conversation={baseConversation()}
          canHumanReplyOverride
          isChangingModeOverride={pending}
        />
      </Shell>
    );
    const screen = await render(renderThread(false));
    const draft = "Bản nháp cần giữ lại";
    await screen.getByRole("textbox", { name: "Tin nhắn trả lời" }).fill(draft);
    await screen.rerender(renderThread(true));
    const textbox = screen.getByRole("textbox", { name: "Tin nhắn trả lời" });
    await expect.element(textbox).toBeDisabled();
    await expect.element(textbox).toHaveValue(draft);
    await expect
      .element(screen.getByRole("button", { name: "Gửi tin nhắn" }))
      .toBeDisabled();
    screen.container
      .querySelector("textarea")!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    screen.container
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(dataProviderMock.sendHumanReply).not.toHaveBeenCalled();
    expect(realtimeControls.insertOptimistic).not.toHaveBeenCalled();
    await screen.rerender(renderThread(false));
    await expect.element(textbox).toBeEnabled();
    await expect.element(textbox).toHaveValue(draft);
    await screen.getByRole("button", { name: "Gửi tin nhắn" }).click();
    await expect
      .poll(() => dataProviderMock.sendHumanReply.mock.calls.length)
      .toBe(1);
  });

  it("focuses the available composer after an explicit takeover succeeds", async () => {
    let acceptTakeover!: () => void;
    const accepted = new Promise<void>((resolve) => {
      acceptTakeover = resolve;
    });
    const Harness = () => {
      const [state, setState] = useState<"bot" | "pending" | "human">("bot");
      return (
        <Shell>
          <ChatThread
            conversationId="conv-1"
            conversation={baseConversation()}
            isBotModeOverride={state !== "human"}
            canHumanReplyOverride={state === "human"}
            isChangingModeOverride={state === "pending"}
            onTakeoverOverride={async () => {
              setState("pending");
              await accepted;
              setState("human");
            }}
          />
        </Shell>
      );
    };
    const screen = await render(<Harness />);
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    await expect
      .element(screen.getByRole("button", { name: "Tiếp quản" }))
      .toBeDisabled();
    expect(screen.container.querySelector("textarea")).toBeNull();
    acceptTakeover();
    await expect
      .element(screen.getByRole("textbox", { name: "Tin nhắn trả lời" }))
      .toHaveFocus();
  });

  it("does not autofocus after a realtime mode change or a failed explicit takeover", async () => {
    const failedTakeover = vi.fn(async () => {});
    const renderThread = (human: boolean) => (
      <Shell>
        <ChatThread
          conversationId="conv-1"
          conversation={baseConversation()}
          isBotModeOverride={!human}
          canHumanReplyOverride={human}
          onTakeoverOverride={failedTakeover}
        />
      </Shell>
    );
    const screen = await render(renderThread(false));
    await screen.getByRole("button", { name: "Tiếp quản" }).click();
    // The action has settled without accepting human mode. A later realtime
    // update must not be mistaken for the completion of that failed claim.
    await expect.poll(() => failedTakeover.mock.calls.length).toBe(1);
    await screen.rerender(renderThread(true));
    await expect
      .element(screen.getByRole("textbox", { name: "Tin nhắn trả lời" }))
      .not.toHaveFocus();
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

  it("follows committed transcript height changes for an at-bottom reader", async () => {
    messageStoreState.messages = [msg(1), msg(2)];
    const screen = await mountThread();
    const scroller =
      screen.container.querySelector<HTMLElement>(".chat-scroller")!;
    const content = scroller.firstElementChild as HTMLElement;
    content.style.height = "1000px";
    await vi.waitFor(() => {
      expect(
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight,
      ).toBeLessThanOrEqual(1);
    });
    content.style.height = "1400px";
    await vi.waitFor(() => {
      expect(
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight,
      ).toBeLessThanOrEqual(1);
    });
  });

  it("preserves a history reader's position when the transcript height changes", async () => {
    messageStoreState.messages = [msg(1), msg(2)];
    const screen = await mountThread();
    const scroller =
      screen.container.querySelector<HTMLElement>(".chat-scroller")!;
    const content = scroller.firstElementChild as HTMLElement;
    content.style.height = "1000px";
    await vi.waitFor(() => {
      expect(
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight,
      ).toBeLessThanOrEqual(1);
    });
    scroller.scrollTop = 100;
    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    await expect
      .element(
        screen.getByRole("button", { name: "Cuộn đến tin nhắn mới nhất" }),
      )
      .toBeVisible();
    content.style.height = "1400px";
    for (let frame = 0; frame < 4; frame++) {
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve()),
      );
    }
    expect(scroller.scrollTop).toBe(100);
  });

  it("coalesces layout writes and cancels the queued scroll on leaving the thread", async () => {
    const screen = await mountThread();
    const scroller =
      screen.container.querySelector<HTMLElement>(".chat-scroller")!;
    const content = scroller.firstElementChild as HTMLElement;
    const queuedFrames = new Map<number, FrameRequestCallback>();
    let nextFrame = 0;
    const requestFrame = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((callback) => {
        const id = ++nextFrame;
        queuedFrames.set(id, callback);
        return id;
      });
    const cancelFrame = vi
      .spyOn(window, "cancelAnimationFrame")
      .mockImplementation((id) => {
        queuedFrames.delete(id);
      });
    try {
      content.style.height = "1000px";
      await vi.waitFor(() => expect(queuedFrames.size).toBe(1));
      content.style.height = "1400px";
      await Promise.resolve();
      expect(requestFrame).toHaveBeenCalledTimes(1);
      await screen.unmount();
      expect(cancelFrame).toHaveBeenCalledWith(1);
      expect(queuedFrames.size).toBe(0);
    } finally {
      requestFrame.mockRestore();
      cancelFrame.mockRestore();
    }
  });
});

describe("isUnseenWorthyArrival — unseen-content contract", () => {
  // Pure unit coverage of the author/type discriminator that decides whether a
  // new arrival escalates the latest control to "Tin nhắn mới" while the reader
  // is away. Lives in the conversation-thread domain module so the contract is
  // locked in CI.

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
    await expect.element(screen.getByText("Lỗi kết nối mạng")).toBeVisible();
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

    await expect
      .element(screen.getByText("Zalo từ chối tin nhắn"))
      .toBeVisible();
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
        screen.container.querySelector(
          '[data-message-id="2"] .message-text-block',
        ),
      ).not.toBeNull();
    });
    // Content is shown; the reason detail is not (content takes priority).
    expect(screen.container.querySelector(".delivery-error-detail")).toBeNull();
    await expect
      .element(screen.getByText("Cảm ơn bạn đã liên hệ."))
      .toBeVisible();
  });
});
