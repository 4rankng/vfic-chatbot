import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type AuthCallback = (data: { token: string | null }) => void;
type SocketOptions = { auth: (cb: AuthCallback) => void };

interface FakeSocketHandle {
  connected: boolean;
  /** Tokens presented to the server, one entry per handshake. */
  handshakes: (string | null)[];
  disconnects: number;
  connect(): FakeSocketHandle;
  disconnect(): FakeSocketHandle;
  emit(): FakeSocketHandle;
  on(): FakeSocketHandle;
  off(): FakeSocketHandle;
  removeAllListeners(): FakeSocketHandle;
}

/**
 * Stand-in for socket.io-client, reproducing the one behaviour the realtime
 * socket depends on: the `auth` callback runs on every connection attempt and
 * its result is what the server receives in the CONNECT handshake
 * (`Socket.onopen()` → `this.auth(cb)` in socket.io-client's source). The
 * recorded tokens are therefore the ones our own callback read from storage.
 */
const fake = vi.hoisted(() => {
  const state = { created: [] as FakeSocketHandle[] };
  const io = (first: unknown, second?: unknown) => {
    const options = (second ?? first) as SocketOptions;
    const socket: FakeSocketHandle = {
      connected: false,
      handshakes: [],
      disconnects: 0,
      // socket.io's Socket methods are chainable (disconnect().connect()).
      connect() {
        if (socket.connected) return socket;
        socket.connected = true;
        options.auth((data) => socket.handshakes.push(data.token));
        return socket;
      },
      disconnect() {
        if (socket.connected) socket.disconnects += 1;
        socket.connected = false;
        return socket;
      },
      emit() {
        return socket;
      },
      on() {
        return socket;
      },
      off() {
        return socket;
      },
      removeAllListeners() {
        return socket;
      },
    };
    state.created.push(socket);
    return socket;
  };
  return { state, io };
});

vi.mock("socket.io-client", () => ({ io: fake.io }));

import { clearTokens, refreshOnce, setTokens } from "@/lib/apiClient";

import { closeRealtimeSocket, getRealtimeSocket } from "./realtime-socket";

const socketAt = (index: number): FakeSocketHandle => fake.state.created[index];

/** Drives the real single-flight refresh, which is what rotates the token. */
const rotateTokens = async (accessToken: string, refreshToken: string) => {
  globalThis.fetch = (async () =>
    new Response(
      JSON.stringify({
        access_token: accessToken,
        refresh_token: refreshToken,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    )) as unknown as typeof globalThis.fetch;
  await expect(refreshOnce()).resolves.toBe(true);
};

describe("realtime socket", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    clearTokens();
    fake.state.created.length = 0;
  });

  afterEach(() => {
    closeRealtimeSocket();
    clearTokens();
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("creates no socket until a subscriber asks for one", () => {
    // Importing this module — and anything importing it, such as the eagerly
    // loaded recruitment capability — must not construct the Manager.
    expect(fake.state.created).toHaveLength(0);

    getRealtimeSocket();

    expect(fake.state.created).toHaveLength(1);
    // autoConnect: false — nothing is presented until a subscriber connects.
    expect(socketAt(0).handshakes).toEqual([]);
  });

  it("reuses one socket across subscribers", () => {
    expect(getRealtimeSocket()).toBe(getRealtimeSocket());
    expect(fake.state.created).toHaveLength(1);
  });

  it("presents the rotated token after a successful refresh", async () => {
    setTokens("access-v1", "refresh-v1");
    const socket = getRealtimeSocket();
    socket.connect();
    expect(socketAt(0).handshakes).toEqual(["access-v1"]);

    await rotateTokens("access-v2", "refresh-v2");

    // The live connection held the old token, so it re-handshook with the new one.
    expect(socketAt(0).handshakes).toEqual(["access-v1", "access-v2"]);
    expect(socketAt(0).disconnects).toBe(1);
  });

  it("leaves a socket that is not connected alone, since its next attempt reads the new token", async () => {
    setTokens("access-v1", "refresh-v1");
    const socket = getRealtimeSocket();

    await rotateTokens("access-v2", "refresh-v2");

    expect(socketAt(0).disconnects).toBe(0);
    expect(socketAt(0).handshakes).toEqual([]);

    socket.connect();
    expect(socketAt(0).handshakes).toEqual(["access-v2"]);
  });

  it("stops re-authenticating once the socket is closed on logout", async () => {
    setTokens("access-v1", "refresh-v1");
    const socket = getRealtimeSocket();
    socket.connect();

    closeRealtimeSocket();

    expect(socketAt(0).disconnects).toBe(1);

    await rotateTokens("access-v2", "refresh-v2");

    expect(socketAt(0).handshakes).toEqual(["access-v1"]);

    // A fresh login builds a new socket that carries the current token.
    const next = getRealtimeSocket();
    expect(next).not.toBe(socket);
    next.connect();
    expect(socketAt(1).handshakes).toEqual(["access-v2"]);
  });
});
