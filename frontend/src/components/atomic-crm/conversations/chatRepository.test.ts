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
}));

import { chatRepository } from "./chatRepository";

/**
 * chatRepository (message history + inbox snippets + realtime subscribe) had
 * zero tests. Covers: newest-first->chronological reversal + sender->type
 * mapping + hasMore, the batched last-messages re-keying, and the Socket.IO
 * room join/leave lifecycle (incl. the no-token no-op short-circuit).
 */
const stubJson = (
  json: () => Promise<unknown>,
): { fetch: typeof globalThis.fetch; lastUrl: () => string } => {
  let url = "";
  const fn = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
    url = typeof input === "string" ? input : (input as URL).toString();
    return { ok: true, status: 200, json: json as () => Promise<unknown> } as unknown as Response;
  });
  return { fetch: fn as unknown as typeof globalThis.fetch, lastUrl: () => url };
};

describe("chatRepository.getConversationMessages", () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearTokens();
    vi.restoreAllMocks();
  });

  it("maps sender->type, reverses to chronological, and flags hasMore on a full page", async () => {
    const { fetch } = stubJson(async () => ({
      // Backend order is newest-first.
      data: [
        { id: 3, body: "c", sender: "WORKER", created_at: "t3" },
        { id: 2, body: "b", sender: "BOT", created_at: "t2" },
        { id: 1, body: "a", sender: "SYSTEM", created_at: "t1" },
      ],
      total: 3,
    }));
    globalThis.fetch = fetch;
    const { messages, hasMore } = await chatRepository.getConversationMessages("c1", {
      limit: 3,
    });
    expect(messages.map((m) => m.id)).toEqual(["1", "2", "3"]); // reversed to chronological
    // Server order is newest-first [id3,id2,id1]; after reverse the oldest (id1)
    // is first. Mapping: SYSTEM->system, BOT->outbound, WORKER->inbound.
    expect(messages[0].type).toBe("system"); // id1 SYSTEM (oldest)
    expect(messages[1].type).toBe("outbound"); // id2 BOT
    expect(messages[2].type).toBe("inbound"); // id3 WORKER (newest)
    expect(hasMore).toBe(true); // full page (3 >= 3)
  });

  it("reports hasMore=false on a partial page", async () => {
    const { fetch } = stubJson(async () => ({ data: [{ id: 1, body: "x", sender: "WORKER" }], total: 1 }));
    globalThis.fetch = fetch;
    const { hasMore } = await chatRepository.getConversationMessages("c1", { limit: 10 });
    expect(hasMore).toBe(false);
  });

  it("sends before_id cursor when loading older history", async () => {
    const { fetch, lastUrl } = stubJson(async () => ({ data: [], total: 0 }));
    globalThis.fetch = fetch;
    await chatRepository.getConversationMessages("c1", { limit: 10, beforeId: "42" });
    expect(lastUrl()).toContain("before_id=42");
  });
});

describe("chatRepository.getLastMessages", () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("re-keys the snippet map by zalo_chat_id", async () => {
    const { fetch } = stubJson(async () => ({ snippets: { "conv-1": "hello" } }));
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
  afterEach(() => {
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

    expect(mockSocket.on).toHaveBeenCalledWith("message.created", expect.any(Function));
    expect(mockSocket.connect).toHaveBeenCalled();
    expect(mockSocket.emit).toHaveBeenCalledWith("join conversation", {
      conversation_id: "c1",
    });

    unsub();
    expect(mockSocket.off).toHaveBeenCalledWith("message.created", expect.any(Function));
    expect(mockSocket.emit).toHaveBeenCalledWith("leave conversation", {
      conversation_id: "c1",
    });
  });
});
