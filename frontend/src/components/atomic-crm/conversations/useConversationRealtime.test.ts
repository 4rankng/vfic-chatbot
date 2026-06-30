import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook } from "vitest-browser-react";

import type { Message } from "../types";

const { mockChatRepository } = vi.hoisted(() => ({
  mockChatRepository: {
    getConversationMessages: vi.fn(),
    subscribeToMessages: vi.fn(() => () => {
      /* cleanup */
    }),
  },
}));

vi.mock("./chatRepository", () => ({
  chatRepository: mockChatRepository,
}));

import {
  mergeChronological,
  mergeRealtimePage,
  useConversationRealtime,
} from "./useConversationRealtime";

const msg = (id: number, conversationId = "c1"): Message => ({
  id: String(id),
  zalo_message_id: String(id),
  conversation_id: conversationId,
  type: id % 2 === 0 ? "outbound" : "inbound",
  content: `${conversationId} message ${id}`,
  data: { recruiter_id: null },
  created_at: `2026-06-29T00:00:${String(id).padStart(2, "0")}.000Z`,
});

type MessagesPage = { messages: Message[]; hasMore: boolean };
type Deferred<T> = {
  promise: Promise<T>;
  reject: (reason?: unknown) => void;
  resolve: (value: T) => void;
};

const deferred = <T,>(): Deferred<T> => {
  let reject!: (reason?: unknown) => void;
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, reject, resolve };
};

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
});

describe("mergeChronological", () => {
  it("returns the same array reference when an incoming duplicate changes nothing", () => {
    const existing = [msg(10), msg(11)];
    const result = mergeChronological(existing, [{ ...existing[1] }]);

    expect(result).toBe(existing);
  });

  it("sorts merged messages by timestamp even when ids point the other way", () => {
    const older = {
      ...msg(2),
      created_at: "2026-06-29T01:22:00.000Z",
    };
    const newer = {
      ...msg(1),
      created_at: "2026-06-29T02:15:00.000Z",
    };

    const result = mergeChronological([], [newer, older]);

    expect(result.map((m) => m.id)).toEqual(["2", "1"]);
  });

  it("replaces a message when only delivery status changes", () => {
    const pending = {
      ...msg(20),
      delivery_status: "pending" as const,
    };
    const sent = {
      ...pending,
      delivery_status: "sent" as const,
    };

    const result = mergeChronological([pending], [sent]);

    expect(result).toHaveLength(1);
    expect(result[0]).not.toBe(pending);
    expect(result[0]).toBe(sent);
    expect(result[0].delivery_status).toBe("sent");
  });
});

describe("mergeRealtimePage", () => {
  it("normalizes an initial realtime page before any history is loaded", () => {
    const older = {
      ...msg(2),
      created_at: "2026-06-29T01:22:00.000Z",
    };
    const newer = {
      ...msg(1),
      created_at: "2026-06-29T02:15:00.000Z",
    };

    const result = mergeRealtimePage([], [newer, older]);

    expect(result.map((m) => m.id)).toEqual(["2", "1"]);
  });

  it("does not backfill older fetched rows into the current visible window", () => {
    const firstLoaded = msg(10);
    const current = [firstLoaded, msg(11), msg(12)];
    const result = mergeRealtimePage(current, [
      msg(1),
      msg(2),
      { ...firstLoaded },
      msg(13),
    ]);

    expect(result.map((m) => m.id)).toEqual(["10", "11", "12", "13"]);
    expect(result[0]).toBe(firstLoaded);
  });
});

describe("useConversationRealtime", () => {
  it("does not let a late response from the previous conversation replace the active thread", async () => {
    const oldPage = deferred<MessagesPage>();
    const nextPage = deferred<MessagesPage>();

    mockChatRepository.getConversationMessages.mockImplementation(
      (conversationId: string) =>
        conversationId === "old-conversation"
          ? oldPage.promise
          : nextPage.promise,
    );

    const hook = await renderHook(
      (props?: { conversationId: string }) =>
        useConversationRealtime(props?.conversationId),
      { initialProps: { conversationId: "old-conversation" } },
    );

    await hook.rerender({ conversationId: "next-conversation" });

    const firstRequestOptions =
      mockChatRepository.getConversationMessages.mock.calls[0]?.[1];
    expect(firstRequestOptions?.signal?.aborted).toBe(true);

    await hook.act(async () => {
      nextPage.resolve({
        messages: [msg(2, "next-conversation")],
        hasMore: false,
      });
      await nextPage.promise;
    });
    expect(hook.result.current.messages.map((message) => message.content)).toEqual([
      "next-conversation message 2",
    ]);

    await hook.act(async () => {
      oldPage.resolve({
        messages: [msg(1, "old-conversation")],
        hasMore: false,
      });
      await oldPage.promise;
    });

    expect(hook.result.current.messages.map((message) => message.content)).toEqual([
      "next-conversation message 2",
    ]);
  });

  it("ignores messages whose conversation_id does not match the active thread", async () => {
    const activePage = deferred<MessagesPage>();
    let pushRealtime: ((messages: Message[]) => void) | undefined;

    mockChatRepository.getConversationMessages.mockReturnValue(activePage.promise);
    mockChatRepository.subscribeToMessages.mockImplementation(
      (...args: unknown[]) => {
        pushRealtime = args[1] as (messages: Message[]) => void;
        return () => {
          /* cleanup */
        };
      },
    );

    const hook = await renderHook(() =>
      useConversationRealtime("active-conversation"),
    );

    await hook.act(async () => {
      pushRealtime?.([msg(1, "other-conversation")]);
    });
    expect(hook.result.current.messages).toEqual([]);

    await hook.act(async () => {
      activePage.resolve({
        messages: [msg(2, "other-conversation")],
        hasMore: false,
      });
      await activePage.promise;
    });
    expect(hook.result.current.messages).toEqual([]);

    await hook.act(async () => {
      pushRealtime?.([msg(3, "active-conversation")]);
    });
    expect(hook.result.current.messages.map((message) => message.content)).toEqual([
      "active-conversation message 3",
    ]);
  });

  it("discards middle-mount late resolve in a 3-way rapid switch (A→B→C, resolve C→A→B)", async () => {
    const pageA = deferred<MessagesPage>();
    const pageB = deferred<MessagesPage>();
    const pageC = deferred<MessagesPage>();

    mockChatRepository.getConversationMessages.mockImplementation(
      (conversationId: string) => {
        if (conversationId === "conv-a") return pageA.promise;
        if (conversationId === "conv-b") return pageB.promise;
        return pageC.promise;
      },
    );

    const hook = await renderHook(
      (props?: { conversationId: string }) =>
        useConversationRealtime(props?.conversationId),
      { initialProps: { conversationId: "conv-a" } },
    );

    // Rapid switch: A → B → C
    await hook.rerender({ conversationId: "conv-b" });
    await hook.rerender({ conversationId: "conv-c" });

    // Earlier requests must be aborted
    expect(
      mockChatRepository.getConversationMessages.mock.calls[0]?.[1]?.signal?.aborted,
    ).toBe(true);
    expect(
      mockChatRepository.getConversationMessages.mock.calls[1]?.[1]?.signal?.aborted,
    ).toBe(true);

    // Resolve in out-of-order: C first
    await hook.act(async () => {
      pageC.resolve({
        messages: [msg(30, "conv-c"), msg(31, "conv-c")],
        hasMore: false,
      });
      await pageC.promise;
    });
    expect(hook.result.current.messages.map((m) => m.content)).toEqual([
      "conv-c message 30",
      "conv-c message 31",
    ]);

    // A resolves late — must be discarded
    await hook.act(async () => {
      pageA.resolve({
        messages: [msg(10, "conv-a"), msg(11, "conv-a")],
        hasMore: false,
      });
      await pageA.promise;
    });
    expect(hook.result.current.messages.map((m) => m.content)).toEqual([
      "conv-c message 30",
      "conv-c message 31",
    ]);

    // B resolves last — must be discarded (middle-mount late resolve)
    await hook.act(async () => {
      pageB.resolve({
        messages: [msg(20, "conv-b"), msg(21, "conv-b")],
        hasMore: false,
      });
      await pageB.promise;
    });
    expect(hook.result.current.messages.map((m) => m.content)).toEqual([
      "conv-c message 30",
      "conv-c message 31",
    ]);
  });
});
