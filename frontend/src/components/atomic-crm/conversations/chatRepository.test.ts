import { afterEach, describe, expect, it, vi } from "vitest";

import { clearTokens, setTokens } from "../providers/rest/api";

// Socket.IO singleton mock. vi.hoisted makes the mock object available to the
// hoisted vi.mock factory (the factory runs before top-level imports).
const { mockSocket } = vi.hoisted(() => ({
  mockSocket: {
    connected: false,
    on: vi.fn(),
    off: vi.fn(),
    emit: vi.fn(),
    connect: vi.fn(),
  },
}));
vi.mock("@/lib/vfic/realtimeSocket", () => ({
  getRealtimeSocket: () => mockSocket,
  closeRealtimeSocket: vi.fn(),
}));

import { chatRepository, RuntimeEpochMismatchError } from "./chatRepository";
import { resetActiveRuntimeState } from "../root/reset-runtime-state";

/**
 * chatRepository (message history + inbox snippets + realtime subscribe) had
 * zero tests. Covers: chronological message history + sender->type
 * mapping + hasMore, the batched last-messages re-keying, and the Socket.IO
 * room join/leave lifecycle (incl. the no-token no-op short-circuit).
 */
const stubJson = (
  json: () => Promise<unknown>,
): {
  fetch: typeof globalThis.fetch;
  lastInit: () => RequestInit | undefined;
  lastUrl: () => string;
} => {
  let url = "";
  let init: RequestInit | undefined;
  const fn = vi.fn(
    async (
      input: RequestInfo | URL,
      requestInit?: RequestInit,
    ): Promise<Response> => {
      url = typeof input === "string" ? input : (input as URL).toString();
      init = requestInit;
      return {
        ok: true,
        status: 200,
        json: json as () => Promise<unknown>,
      } as unknown as Response;
    },
  );
  return {
    fetch: fn as unknown as typeof globalThis.fetch,
    lastInit: () => init,
    lastUrl: () => url,
  };
};

const messageCreatedHandler = () => {
  const call = mockSocket.on.mock.calls.find(
    ([event]) => event === "message.created",
  );
  if (!call) throw new Error("message.created handler was not registered");
  return call[1] as (payload: unknown) => void;
};

describe("chatRepository.getConversationMessages", () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearTokens();
    vi.restoreAllMocks();
  });

  it("sorts API messages chronologically, maps delivery attempts and sender->type, and flags hasMore on a full page", async () => {
    const { fetch } = stubJson(async () => ({
      // Guard against a scrambled page: visible time must move forward
      // top-to-bottom even when id order would put 02:15 before 01:22.
      data: [
        {
          id: 1,
          conversation_id: "c1",
          body: "b",
          sender: "BOT",
          delivery_attempts: 3,
          created_at: "2026-06-29T02:15:00.000Z",
        },
        {
          id: 2,
          conversation_id: "c1",
          body: "a",
          sender: "SYSTEM",
          created_at: "2026-06-29T01:22:00.000Z",
        },
        {
          id: 3,
          conversation_id: "c1",
          body: "c",
          sender: "WORKER",
          created_at: "2026-06-29T13:41:00.000Z",
        },
      ],
      total: 3,
    }));
    globalThis.fetch = fetch;
    const { messages, hasMore } = await chatRepository.getConversationMessages(
      "c1",
      {
        limit: 3,
      },
    );
    expect(messages.map((m) => m.id)).toEqual(["2", "1", "3"]);
    // Mapping: SYSTEM->system, BOT->outbound, WORKER->inbound.
    expect(messages[0].type).toBe("system"); // id2 SYSTEM (oldest)
    expect(messages[1].type).toBe("outbound"); // id1 BOT
    expect(messages[1].delivery_attempts).toBe(3);
    expect(messages[2].type).toBe("inbound"); // id3 WORKER (newest)
    expect(hasMore).toBe(true); // full page (3 >= 3)
  });

  it("treats candidate sender variants and inbound direction as inbound", async () => {
    const { fetch } = stubJson(async () => ({
      data: [
        {
          id: 4,
          conversation_id: "c1",
          body: "fallback inbound",
          sender: null,
          created_at: "t4",
        },
        {
          id: 3,
          conversation_id: "c1",
          body: "direction inbound",
          direction: "inbound",
          created_at: "t3",
        },
        {
          id: 2,
          conversation_id: "c1",
          body: "candidate",
          sender: "CANDIDATE",
          created_at: "t2",
        },
        {
          id: 1,
          conversation_id: "c1",
          body: "worker",
          sender: "WORKER",
          created_at: "t1",
        },
      ],
      total: 4,
    }));
    globalThis.fetch = fetch;

    const { messages } = await chatRepository.getConversationMessages("c1", {
      limit: 10,
    });

    expect(messages.map((m) => m.type)).toEqual([
      "inbound",
      "inbound",
      "inbound",
      "inbound",
    ]);
  });

  it("reports hasMore=false on a partial page", async () => {
    const { fetch } = stubJson(async () => ({
      data: [{ id: 1, conversation_id: "c1", body: "x", sender: "WORKER" }],
      total: 1,
    }));
    globalThis.fetch = fetch;
    const { hasMore } = await chatRepository.getConversationMessages("c1", {
      limit: 10,
    });
    expect(hasMore).toBe(false);
  });

  it("sends before cursor when loading older history", async () => {
    const { fetch, lastUrl } = stubJson(async () => ({ data: [], total: 0 }));
    globalThis.fetch = fetch;
    await chatRepository.getConversationMessages("c1", {
      limit: 10,
      beforeId: "42",
    });
    expect(lastUrl()).toContain("limit=10");
    expect(lastUrl()).toContain("before=42");
  });

  it("passes AbortSignal through to the HTTP request", async () => {
    const controller = new AbortController();
    const { fetch, lastInit } = stubJson(async () => ({ data: [], total: 0 }));
    globalThis.fetch = fetch;

    await chatRepository.getConversationMessages("c1", {
      limit: 10,
      signal: controller.signal,
    });

    expect(lastInit()?.signal).toBe(controller.signal);
  });

  it("drops messages that do not belong to the requested conversation", async () => {
    const { fetch } = stubJson(async () => ({
      data: [
        { id: 1, conversation_id: "other", body: "wrong", sender: "WORKER" },
        { id: 2, conversation_id: "c1", body: "right", sender: "WORKER" },
      ],
      total: 2,
    }));
    globalThis.fetch = fetch;

    const { messages } = await chatRepository.getConversationMessages("c1", {
      limit: 10,
    });

    expect(messages.map((message) => message.content)).toEqual(["right"]);
  });

  it("maps external_error and preserves send_unknown delivery_status", async () => {
    // A failed send carries the backend failure reason (messages.external_error)
    // so a "Gửi lỗi" bubble is diagnosable. SEND_UNKNOWN must round-trip (the
    // old type cast dropped it from the union, leaving the runtime string intact
    // but unsoundly typed).
    const { fetch } = stubJson(async () => ({
      data: [
        {
          id: 1,
          conversation_id: "c1",
          body: "",
          sender: "BOT",
          delivery_status: "FAILED",
          external_error: "zalo rejected: OA quota exceeded",
          created_at: "2026-07-15T16:52:00.000Z",
        },
        {
          id: 2,
          conversation_id: "c1",
          body: "đã gửi",
          sender: "BOT",
          delivery_status: "SEND_UNKNOWN",
          created_at: "2026-07-15T16:53:00.000Z",
        },
      ],
      total: 2,
    }));
    globalThis.fetch = fetch;

    const { messages } = await chatRepository.getConversationMessages("c1", {
      limit: 10,
    });

    const failed = messages.find((m) => m.id === "1");
    expect(failed?.delivery_status).toBe("failed");
    expect(failed?.external_error).toBe("zalo rejected: OA quota exceeded");

    const unknown = messages.find((m) => m.id === "2");
    expect(unknown?.delivery_status).toBe("send_unknown");
    expect(unknown?.external_error).toBeNull();
  });

  it("rejects a late direct response after the runtime epoch advances", async () => {
    let resolveJson: ((value: unknown) => void) | undefined;
    const json = new Promise<unknown>((resolve) => {
      resolveJson = resolve;
    });
    const { fetch } = stubJson(() => json);
    globalThis.fetch = fetch;
    const pending = chatRepository.getConversationMessages("c1");

    await resetActiveRuntimeState();
    resolveJson?.({
      data: [{ id: 1, conversation_id: "c1", body: "stale", sender: "WORKER" }],
      total: 1,
    });

    await expect(pending).rejects.toBeInstanceOf(RuntimeEpochMismatchError);
  });
});

describe("chatRepository.getLastMessages", () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("re-keys the snippet map by zalo_chat_id", async () => {
    const { fetch } = stubJson(async () => ({
      snippets: { "conv-1": "hello" },
    }));
    globalThis.fetch = fetch;
    const out = await chatRepository.getLastMessages([
      { id: "conv-1", zalo_chat_id: "z-1" },
      { id: "conv-2", zalo_chat_id: "z-2" },
    ]);
    expect(out).toEqual({ "z-1": "hello" });
  });

  it("returns an empty map (no throw) when there are no valid conversations", async () => {
    const { fetch } = stubJson(async () => ({ snippets: { x: "y" } }));
    globalThis.fetch = fetch;
    const out = await chatRepository.getLastMessages([]);
    expect(out).toEqual({});
  });
});

describe("chatRepository.subscribeToMessages", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
    vi.clearAllMocks();
    clearTokens();
    mockSocket.connected = false;
  });

  it("is a no-op when there is no access token (never touches the socket)", () => {
    clearTokens();
    const unsub = chatRepository.subscribeToMessages("c1", () => {});
    expect(mockSocket.on).not.toHaveBeenCalled();
    expect(mockSocket.emit).not.toHaveBeenCalled();
    expect(() => unsub()).not.toThrow();
  });

  it("joins the room, connects lazily, and leaves on unsubscribe", () => {
    setTokens("access", "refresh");
    const unsub = chatRepository.subscribeToMessages("c1", () => {});

    expect(mockSocket.on).toHaveBeenCalledWith(
      "message.created",
      expect.any(Function),
    );
    expect(mockSocket.connect).toHaveBeenCalled();
    expect(mockSocket.emit).toHaveBeenCalledWith("join conversation", {
      conversation_id: "c1",
    });

    unsub();
    expect(mockSocket.off).toHaveBeenCalledWith(
      "message.created",
      expect.any(Function),
    );
    expect(mockSocket.emit).toHaveBeenCalledWith("leave conversation", {
      conversation_id: "c1",
    });
  });

  it("uses a full realtime message payload without refetching latest history", () => {
    setTokens("access", "refresh");
    globalThis.fetch = vi.fn() as unknown as typeof globalThis.fetch;
    const onMessages = vi.fn();

    chatRepository.subscribeToMessages("c1", onMessages);
    messageCreatedHandler()({
      conversation_id: "c1",
      message_id: 7,
      message: {
        id: 7,
        conversation_id: "c1",
        sender: "BOT",
        body: "Xin chào",
        created_at: "2026-06-29T01:02:03.000Z",
      },
    });

    expect(onMessages).toHaveBeenCalledWith([
      expect.objectContaining({
        id: "7",
        conversation_id: "c1",
        type: "outbound",
        content: "Xin chào",
        created_at: "2026-06-29T01:02:03.000Z",
      }),
    ]);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("keeps a debounced latest-page fetch for legacy id-only payloads", async () => {
    vi.useFakeTimers();
    setTokens("access", "refresh");
    const { fetch } = stubJson(async () => ({
      data: [
        {
          id: 8,
          conversation_id: "c1",
          sender: "WORKER",
          body: "Legacy refresh",
          created_at: "2026-06-29T01:02:04.000Z",
        },
      ],
      total: 1,
    }));
    globalThis.fetch = fetch;
    const onMessages = vi.fn();

    chatRepository.subscribeToMessages("c1", onMessages);
    const handler = messageCreatedHandler();
    handler({ conversation_id: "c1", message_id: 8 });
    handler({ conversation_id: "c1", message_id: 8 });

    expect(globalThis.fetch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(80);
    await Promise.resolve();
    await Promise.resolve();

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(onMessages).toHaveBeenCalledWith([
      expect.objectContaining({
        id: "8",
        conversation_id: "c1",
        type: "inbound",
        content: "Legacy refresh",
      }),
    ]);
  });
});
