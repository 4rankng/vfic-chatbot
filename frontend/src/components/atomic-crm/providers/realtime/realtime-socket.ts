// Singleton Socket.IO client for realtime chat (replaces the SSE EventSource).
//
// One socket serves the whole inbox: conversations are server-side rooms, so a
// subscription just joins/leaves a `conv:<id>` room. The access JWT rides in
// the `auth` handshake and is re-read on every (re)connect, so a refreshed
// token after expiry is picked up without re-creating the socket. A connection
// that is already open keeps the token from its original handshake, so a
// rotation (see `onAccessTokenRotated`) forces a re-handshake instead.
// autoConnect is false — the socket is opened lazily by the first subscriber
// (and only when a session token exists), avoiding reconnect spam when logged
// out. Creating the socket is itself lazy: no Manager exists until the first
// subscriber, so importing this module costs nothing.

import { getAccessToken, onAccessTokenRotated } from "@/lib/apiClient";
import { vficConfig } from "@/lib/runtime-config";

import { io, type Socket } from "socket.io-client";

/** The Socket.IO client handle realtime subscribers talk to (see below). */
export type RealtimeSocket = Socket;

let socket: Socket | null = null;
let unsubscribeTokenRotation: (() => void) | null = null;

/**
 * The server reads the JWT once, at connect, so a live connection can only be
 * re-authenticated with a new handshake: `disconnect()` + `connect()` re-runs
 * the `auth` callback with the current token. Emits buffered during the gap are
 * flushed on connect, and `connect` fires again for subscribers that rejoin
 * their rooms. A socket that is not connected is left untouched — its next
 * attempt already reads the new token.
 */
const reauthenticate = (): void => {
  if (!socket?.connected) return;
  socket.disconnect().connect();
};

/**
 * Lazily create (or return the existing) realtime socket. The auth callback is
 * invoked by socket.io-client at each connection attempt, so it always sends
 * the current access token.
 */
export const getRealtimeSocket = (): Socket => {
  if (socket) return socket;
  const options = {
    auth: (cb: (data: { token: string | null }) => void) =>
      cb({ token: getAccessToken() }),
    transports: ["websocket", "polling"],
    autoConnect: false,
    reconnection: true,
  };
  const base = vficConfig.socketUrl;
  socket = base ? io(base, options) : io(options);
  unsubscribeTokenRotation = onAccessTokenRotated(reauthenticate);
  return socket;
};

/** Disconnect and drop the singleton (e.g. on logout). Safe to call when idle. */
export const closeRealtimeSocket = (): void => {
  unsubscribeTokenRotation?.();
  unsubscribeTokenRotation = null;
  if (!socket) return;
  socket.removeAllListeners();
  socket.disconnect();
  socket = null;
};
