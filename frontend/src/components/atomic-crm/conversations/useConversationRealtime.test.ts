import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook } from "vitest-browser-react";

import type { Message } from "../types";

const { mockChatRepository } = vi.hoisted(() => ({
  mockChatRepository: {
    getConversationMessages: vi.fn(),
    getMessagesSince: vi.fn(),
    getLastMessages: vi.fn(),
    getMessageCount: vi.fn(),
    isConnected: vi.fn(() => false),
    subscribeToMessages: vi.fn(() => () => {
      /* cleanup */
    }),
    subscribeToConnection: vi.fn(
      (_onConnect: () => void, _onDisconnect: () => void) => () => {
        /* cleanup */
      },
    ),
  },
}));

import { mergeChronological, mergeRealtimePage } from "./messageOrdering";
import { useConversationRealtime } from "./presentation/use-conversation-realtime";
import { useMessageStore } from "./infrastructure/message-store";
import {
  bindConversationApplication,
  getConversationMessageState,
  type ConversationMessageStatePort,
} from "./application/conversation-runtime";
import type { ConversationMessageRepository } from "./application/ports";
import {
  conversationMessageStatePort,
  MAX_CACHED_CONVERSATIONS,
} from "./infrastructure/message-store";

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

const deferred = <T>(): Deferred<T> => {
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

beforeEach(() => {
  bindConversationApplication({
    messageRepository:
      mockChatRepository as unknown as ConversationMessageRepository,
    messageStatePort:
      conversationMessageStatePort as ConversationMessageStatePort,
  });
  useMessageStore.setState({
    conversations: new Map(),
    pendingOptimistic: new Map(),
  });
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
    expect(
      hook.result.current.messages.map((message) => message.content),
    ).toEqual(["next-conversation message 2"]);

    await hook.act(async () => {
      oldPage.resolve({
        messages: [msg(1, "old-conversation")],
        hasMore: false,
      });
      await oldPage.promise;
    });

    expect(
      hook.result.current.messages.map((message) => message.content),
    ).toEqual(["next-conversation message 2"]);
  });

  it("ignores messages whose conversation_id does not match the active thread", async () => {
    const activePage = deferred<MessagesPage>();
    let pushRealtime: ((messages: Message[]) => void) | undefined;

    mockChatRepository.getConversationMessages.mockReturnValue(
      activePage.promise,
    );
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
    expect(
      hook.result.current.messages.map((message) => message.content),
    ).toEqual(["active-conversation message 3"]);
  });

  it("removes a pending optimistic human reply when the server echo has a new id and timestamp", async () => {
    const activePage = deferred<MessagesPage>();
    let pushRealtime: ((messages: Message[]) => void) | undefined;

    mockChatRepository.getConversationMessages.mockReturnValue(
      activePage.promise,
    );
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
      activePage.resolve({ messages: [], hasMore: false });
      await activePage.promise;
    });

    await hook.act(async () => {
      hook.result.current.insertOptimistic("chào bạn", "recruiter-1");
    });
    expect(hook.result.current.messages).toHaveLength(1);
    expect(hook.result.current.messages[0].id).toMatch(/^optimistic-/);

    await hook.act(async () => {
      pushRealtime?.([
        {
          id: "server-100",
          zalo_message_id: "zalo-100",
          conversation_id: "active-conversation",
          type: "outbound",
          content: "chào bạn",
          delivery_status: "sent",
          data: { recruiter_id: "recruiter-1" },
          created_at: new Date(Date.now() + 1000).toISOString(),
        },
      ]);
    });

    expect(hook.result.current.messages).toHaveLength(1);
    expect(hook.result.current.messages[0].id).toBe("server-100");
    expect(hook.result.current.messages[0].delivery_status).toBe("sent");
  });

  it("replaces a locally failed optimistic reply when its server echo arrives", async () => {
    const activePage = deferred<MessagesPage>();
    let pushRealtime: ((messages: Message[]) => void) | undefined;

    mockChatRepository.getConversationMessages.mockReturnValue(
      activePage.promise,
    );
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
      activePage.resolve({ messages: [], hasMore: false });
      await activePage.promise;
    });

    let tempId = "";
    await hook.act(async () => {
      tempId = hook.result.current.insertOptimistic("chào bạn", "recruiter-1");
      hook.result.current.markOptimisticFailed(tempId);
    });
    expect(hook.result.current.messages[0].delivery_status).toBe("failed");

    await hook.act(async () => {
      pushRealtime?.([
        {
          id: "server-101",
          zalo_message_id: "zalo-101",
          conversation_id: "active-conversation",
          type: "outbound",
          content: "chào bạn",
          delivery_status: "failed",
          delivery_attempts: 2,
          data: { recruiter_id: "recruiter-1" },
          created_at: new Date(Date.now() + 1000).toISOString(),
        },
      ]);
    });

    expect(hook.result.current.messages).toHaveLength(1);
    expect(hook.result.current.messages[0]).toMatchObject({
      id: "server-101",
      delivery_status: "failed",
      delivery_attempts: 2,
    });
  });

  it("pages through every missed message after reconnect", async () => {
    let reconnect: (() => void | Promise<void>) | undefined;
    mockChatRepository.isConnected.mockReturnValue(false);
    mockChatRepository.subscribeToConnection.mockImplementation(
      (onConnect: () => void | Promise<void>) => {
        reconnect = onConnect;
        return () => {
          /* cleanup */
        };
      },
    );
    mockChatRepository.getConversationMessages.mockResolvedValue({
      messages: [msg(1, "active-conversation")],
      hasMore: false,
    });
    const firstMissedPage = Array.from({ length: 200 }, (_, index) => ({
      ...msg(index + 2, "active-conversation"),
      created_at: new Date(
        Date.UTC(2026, 5, 29, 0, 0, 1, index + 2),
      ).toISOString(),
    }));
    const finalMissedMessage = {
      ...msg(202, "active-conversation"),
      created_at: new Date(Date.UTC(2026, 5, 29, 0, 0, 1, 202)).toISOString(),
    };
    mockChatRepository.getMessagesSince
      .mockResolvedValueOnce({
        messages: firstMissedPage,
        hasMore: true,
      })
      .mockResolvedValueOnce({
        messages: [finalMissedMessage],
        hasMore: false,
      });

    const hook = await renderHook(() =>
      useConversationRealtime("active-conversation"),
    );
    await vi.waitFor(() => {
      expect(hook.result.current.messages).toHaveLength(1);
    });

    await hook.act(async () => {
      await reconnect?.();
    });

    expect(mockChatRepository.getMessagesSince).toHaveBeenNthCalledWith(
      1,
      "active-conversation",
      "1",
    );
    expect(mockChatRepository.getMessagesSince).toHaveBeenNthCalledWith(
      2,
      "active-conversation",
      "201",
    );
    expect(hook.result.current.messages).toHaveLength(202);
    expect(hook.result.current.messages.at(-1)?.id).toBe("202");
  });

  it("keeps successful reconnect pages when a later page fails", async () => {
    let reconnect: (() => void | Promise<void>) | undefined;
    mockChatRepository.isConnected.mockReturnValue(false);
    mockChatRepository.subscribeToConnection.mockImplementation(
      (onConnect: () => void | Promise<void>) => {
        reconnect = onConnect;
        return () => {
          /* cleanup */
        };
      },
    );
    mockChatRepository.getConversationMessages.mockResolvedValue({
      messages: [msg(1, "active-conversation")],
      hasMore: false,
    });
    const recoveredPage = Array.from({ length: 200 }, (_, index) => ({
      ...msg(index + 2, "active-conversation"),
      created_at: new Date(
        Date.UTC(2026, 5, 29, 0, 0, 1, index + 2),
      ).toISOString(),
    }));
    mockChatRepository.getMessagesSince
      .mockResolvedValueOnce({
        messages: recoveredPage,
        hasMore: true,
      })
      .mockRejectedValueOnce(new Error("temporary reconnect failure"));

    const hook = await renderHook(() =>
      useConversationRealtime("active-conversation"),
    );
    await vi.waitFor(() => {
      expect(hook.result.current.messages).toHaveLength(1);
    });

    await hook.act(async () => {
      await reconnect?.();
    });

    expect(hook.result.current.messages).toHaveLength(201);
    expect(hook.result.current.messages.at(-1)?.id).toBe("201");
  });

  it("does not let load-more completion mutate the store after unmount", async () => {
    const lateHistory = deferred<MessagesPage>();
    mockChatRepository.getConversationMessages
      .mockResolvedValueOnce({
        messages: [msg(10, "active-conversation")],
        hasMore: true,
      })
      .mockReturnValueOnce(lateHistory.promise);

    const hook = await renderHook(() =>
      useConversationRealtime("active-conversation"),
    );
    await vi.waitFor(() => {
      expect(hook.result.current.hasMore).toBe(true);
    });

    let pendingHistory!: Promise<void>;
    await hook.act(async () => {
      pendingHistory = hook.result.current.loadMore("10");
      await Promise.resolve();
    });
    await cleanup();

    useMessageStore
      .getState()
      .setMessages(
        "active-conversation",
        [msg(99, "active-conversation")],
        false,
      );
    lateHistory.resolve({
      messages: [msg(9, "active-conversation")],
      hasMore: true,
    });
    await pendingHistory;

    const current = useMessageStore
      .getState()
      .conversations.get("active-conversation");
    expect(current?.sortedCache.map((message) => message.id)).toEqual(["99"]);
    expect(current?.hasMore).toBe(false);
    expect(current?.historyError).toBeNull();
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
      mockChatRepository.getConversationMessages.mock.calls[0]?.[1]?.signal
        ?.aborted,
    ).toBe(true);
    expect(
      mockChatRepository.getConversationMessages.mock.calls[1]?.[1]?.signal
        ?.aborted,
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

  it("evicts the least recently used conversation once the cache bound is exceeded", async () => {
    mockChatRepository.getConversationMessages.mockImplementation(
      (conversationId: string) =>
        Promise.resolve({
          messages: [msg(1, conversationId)],
          hasMore: false,
        }),
    );

    const hook = await renderHook(
      (props?: { conversationId: string }) =>
        useConversationRealtime(props?.conversationId),
      { initialProps: { conversationId: "conv-0" } },
    );

    for (let index = 1; index <= MAX_CACHED_CONVERSATIONS; index += 1) {
      const conversationId = `conv-${index}`;
      await hook.rerender({ conversationId });
      await vi.waitFor(() => {
        expect(
          useMessageStore.getState().conversations.get(conversationId)
            ?.isLoading,
        ).toBe(false);
      });
    }

    const cachedIds = Array.from(
      useMessageStore.getState().conversations.keys(),
    );
    expect(cachedIds).toHaveLength(MAX_CACHED_CONVERSATIONS);
    expect(cachedIds).not.toContain("conv-0");
    expect(cachedIds.at(-1)).toBe(`conv-${MAX_CACHED_CONVERSATIONS}`);

    // The evicted conversation is cold again, so returning to it refetches.
    const callsBeforeReopen =
      mockChatRepository.getConversationMessages.mock.calls.length;
    await hook.rerender({ conversationId: "conv-0" });
    expect(mockChatRepository.getConversationMessages.mock.calls.length).toBe(
      callsBeforeReopen + 1,
    );
  });
});

describe("message store cache bound", () => {
  const seedConversation = (conversationId: string) => {
    useMessageStore.getState().reset(conversationId);
    useMessageStore
      .getState()
      .setMessages(conversationId, [msg(1, conversationId)], false);
  };

  it("keeps the conversation being opened — with its in-flight optimistic message — and clears the least recently used one", () => {
    for (let index = 0; index <= MAX_CACHED_CONVERSATIONS; index += 1) {
      seedConversation(`c${index}`);
    }
    const active = "c0"; // seeded first, so it is the least recently used
    const optimisticId = "optimistic-in-flight";
    useMessageStore.getState().addPendingOptimistic(active, optimisticId);
    useMessageStore
      .getState()
      .upsert(active, [{ ...msg(99, active), id: optimisticId }]);

    useMessageStore.getState().touchConversation(active);

    const state = useMessageStore.getState();
    expect(Array.from(state.conversations.keys())).toHaveLength(
      MAX_CACHED_CONVERSATIONS,
    );
    expect(state.conversations.get(active)?.byId.has(optimisticId)).toBe(true);
    expect(state.pendingOptimistic.get(active)?.has(optimisticId)).toBe(true);
    // The victim is the entry that was least recently used, not the active one.
    expect(state.conversations.has("c1")).toBe(false);
    expect(state.pendingOptimistic.has("c1")).toBe(false);
  });

  it("notifies a subscriber only for the conversation slice it selected", () => {
    seedConversation("c-a");
    seedConversation("c-b");
    const listener = vi.fn();
    const unsubscribe = getConversationMessageState().subscribeTo(
      (state) => state.conversations.get("c-b")?.sortedCache,
      listener,
    );

    useMessageStore.getState().reset("c-a");
    useMessageStore.getState().setLoading("c-b", true);
    expect(listener).not.toHaveBeenCalled();

    useMessageStore.getState().upsert("c-b", [msg(2, "c-b")]);
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
  });
});
